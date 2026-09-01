/**
 * sync_recipients.gs — Google Apps Script
 * =========================================
 * Synchronise la liste des destinataires de la newsletter depuis
 * la Google Sheet liée au formulaire d'inscription vers le fichier
 * config/recipients.toml du dépôt GitHub.
 *
 * Déclencheurs — il en faut DEUX, et le second n'est pas optionnel :
 *
 *   1. « À l'envoi du formulaire » → onFormSubmit
 *      Couvre les inscriptions faites dans l'interface Google Forms.
 *
 *   2. « Horaire », toutes les 15 minutes → syncRecipients
 *      Couvre les inscriptions venues de la landing page /inscription.
 *      Un POST direct vers /formResponse crée bien une réponse dans la
 *      Sheet, mais NE déclenche PAS onFormSubmit (vérifié le 27/08/2026 :
 *      ligne créée, aucune exécution dans le journal). Sans ce second
 *      déclencheur, ces inscriptions restent dans la Sheet et n'atteignent
 *      jamais recipients.toml.
 *
 * La synchronisation relit la Sheet entière et n'écrit que s'il y a du
 * nouveau : la lancer sur une horloge est sans effet de bord, et deux
 * déclencheurs qui se croisent ne produisent pas de doublon.
 *
 * Configuration requise (Fichier → Propriétés du projet → Propriétés du script) :
 *   GITHUB_TOKEN     — Personal Access Token GitHub avec scope "repo"
 *   GOOGLE_SHEET_ID  — ID de la Google Sheet (visible dans l'URL de la Sheet)
 *   EMAIL_COLUMN     — Nom exact de la colonne email dans la Sheet
 *                      (défaut: "Question 1 — Email")
 *
 * Dépôt cible :
 *   GITHUB_OWNER  — Propriétaire du repo (défaut: "yousmaaza")
 *   GITHUB_REPO   — Nom du repo (défaut: "newletter-ai")
 *   GITHUB_BRANCH — Branche cible (défaut: "main")
 *   RECIPIENTS_PATH — Chemin du fichier TOML (défaut: "config/recipients.toml")
 */

// ─── Configuration ────────────────────────────────────────────────────────────

var CONFIG = {
  GITHUB_OWNER:        "yousmaaza",
  GITHUB_REPO:         "newsletter-data",   // dépôt PRIVÉ dédié (#55)
  GITHUB_BRANCH:       "main",
  RECIPIENTS_PATH:     "config/recipients.toml",
  UNSUBSCRIBED_PATH:   "config/unsubscribed.toml",
  EMAIL_COLUMN:        "Question 1 — Email",   // Nom de la colonne dans la Sheet
  TIMESTAMP_COLUMN:    "Horodateur",            // Colonne de date/heure du formulaire
  UNSUBSCRIBED_COLUMN: "Désinscrit",            // Colonne de statut ajoutée automatiquement
  OWNER_EMAIL:         "REDACTED", // Destinataire des notifications
};

// ─── Points d'entrée ──────────────────────────────────────────────────────────

/**
 * À connecter au déclencheur "À l'envoi du formulaire".
 *
 * L'événement `e` n'est volontairement pas utilisé : la synchronisation relit
 * la Sheet entière. C'est ce qui permet à syncRecipients() de faire le même
 * travail sur une horloge.
 */
function onFormSubmit(e) {
  syncRecipients();
}

/**
 * À connecter au déclencheur "Horaire" (toutes les 15 minutes).
 *
 * Fusionne les emails du form avec ceux déjà présents dans recipients.toml
 * (ajouts manuels inclus) et ne commit que si de nouveaux emails sont détectés.
 *
 * ⚠️ Ne jamais faire dépendre cette fonction d'un événement de soumission :
 * elle tourne aussi sans, et c'est le seul chemin par lequel les inscriptions
 * de la landing page atteignent recipients.toml.
 */
function syncRecipients() {
  try {
    var token           = getToken_();
    // Avant toute lecture : sans cette vérification, un 404 d'accès serait
    // confondu avec un fichier absent, et les listes seraient lues vides.
    assertRepoReachable_(token);
    var recipientsUrl   = buildApiUrl_(CONFIG.RECIPIENTS_PATH);
    var unsubscribedUrl = buildApiUrl_(CONFIG.UNSUBSCRIBED_PATH);

    var fromSheet = collectEmails_();
    Logger.log("Emails depuis la Sheet : " + fromSheet.length);

    var fromGit = getExistingEmails_(recipientsUrl, token);
    Logger.log("Emails déjà dans recipients.toml : " + fromGit.length);

    // Lecture de la liste noire {email: iso_timestamp}
    var unsubscribedMap = getUnsubscribedEmailsWithTimestamps_(unsubscribedUrl, token);
    Logger.log("Emails désinscrits : " + Object.keys(unsubscribedMap).length);

    // ── Détection des réinscriptions ─────────────────────────────────────────
    // Comparer le dernier horodatage du formulaire avec le timestamp de désinscription
    var latestByEmail  = getLatestSubmissionByEmail_();
    var resubscribed   = [];

    Object.keys(unsubscribedMap).forEach(function(email) {
      var unsubTs  = unsubscribedMap[email] ? new Date(unsubscribedMap[email]) : null;
      var submitTs = latestByEmail[email];
      if (submitTs && unsubTs && submitTs > unsubTs) {
        resubscribed.push(email);
        Logger.log("Réinscription détectée : " + email +
                   " (form: " + submitTs.toISOString() +
                   " > unsub: " + unsubTs.toISOString() + ")");
      }
    });

    if (resubscribed.length > 0) {
      removeFromUnsubscribed_(resubscribed, unsubscribedUrl, token);
      resubscribed.forEach(function(e) { delete unsubscribedMap[e]; });
      sendResubscribeNotification_(resubscribed);
      Logger.log("Réinscrits et retirés de la liste noire : " + resubscribed.join(", "));
    }

    // ── Mise à jour de recipients.toml ───────────────────────────────────────
    var unsubscribedSet = {};
    Object.keys(unsubscribedMap).forEach(function(e) { unsubscribedSet[e] = true; });

    var merged = mergeEmails_(fromGit, fromSheet);
    merged = merged.filter(function(e) { return !unsubscribedSet[e]; });

    var fromGitSet = {};
    fromGit.forEach(function(e) { fromGitSet[e] = true; });
    var newEmails = merged.filter(function(e) { return !fromGitSet[e]; });
    var added = newEmails.length;

    if (added === 0 && resubscribed.length === 0) {
      Logger.log("Aucun changement — recipients.toml inchangé.");
    } else if (added > 0 || resubscribed.length > 0) {
      // Forcer la mise à jour si des réinscriptions ont eu lieu
      var shouldUpdate = added > 0 || resubscribed.some(function(e) { return !fromGitSet[e]; });
      if (shouldUpdate || resubscribed.length > 0) {
        Logger.log("Mise à jour recipients.toml (" + merged.length + " destinataires)...");
        updateRecipientsFile_(merged, recipientsUrl, token);
      }
    }

    // Mise à jour de la colonne "Désinscrit" dans la Sheet
    markUnsubscribedInSheet_(unsubscribedSet);

  } catch (err) {
    Logger.log("Erreur sync_recipients : " + err.message);
    throw err;
  }
}

// ─── Accès au dépôt ───────────────────────────────────────────────────────────

/**
 * Vérifie que le dépôt de données est lisible AVANT toute lecture de fichier.
 *
 * Indispensable : GitHub renvoie 404 aussi bien pour « fichier absent » que
 * pour « jeton sans accès ». Sans cette vérification, un jeton mal configuré
 * fait lire des listes vides — et la synchronisation RÉINSCRIT les désabonnés.
 * Constaté le 27 août 2026 : seul l'échec de l'écriture l'a évité.
 */
function assertRepoReachable_(token) {
  var url = "https://api.github.com/repos/" + CONFIG.GITHUB_OWNER + "/" + CONFIG.GITHUB_REPO;
  var response = UrlFetchApp.fetch(url, {
    headers:            { "Authorization": "token " + token },
    muteHttpExceptions: true,
  });
  var code = response.getResponseCode();
  if (code !== 200) {
    throw new Error(
      "Dépôt " + CONFIG.GITHUB_OWNER + "/" + CONFIG.GITHUB_REPO + " inaccessible " +
      "(HTTP " + code + "). Le GITHUB_TOKEN des propriétés du script n'a probablement " +
      "pas accès à ce dépôt. Synchronisation interrompue — poursuivre réinscrirait " +
      "les désabonnés."
    );
  }
}

// ─── Lecture des emails depuis la Sheet ───────────────────────────────────────

/**
 * Lit toutes les réponses de la Sheet et retourne la liste
 * d'emails dédupliqués et validés.
 * Utilise GOOGLE_SHEET_ID depuis les propriétés du script pour ouvrir
 * la Sheet explicitement (fonctionne en run manuel et en déclencheur).
 */
function collectEmails_() {
  var sheetId = PropertiesService.getScriptProperties().getProperty("GOOGLE_SHEET_ID");
  if (!sheetId) {
    throw new Error(
      "GOOGLE_SHEET_ID manquant. " +
      "Aller dans Fichier → Propriétés du projet → Propriétés du script."
    );
  }
  var spreadsheet = SpreadsheetApp.openById(sheetId);
  var sheet = spreadsheet.getActiveSheet();
  var data  = sheet.getDataRange().getValues();

  if (data.length < 2) return [];  // Seulement la ligne d'en-tête

  var headerRow = data[0];
  var emailCol  = headerRow.indexOf(CONFIG.EMAIL_COLUMN);

  if (emailCol === -1) {
    throw new Error(
      "Colonne \"" + CONFIG.EMAIL_COLUMN + "\" introuvable. " +
      "Vérifier la propriété EMAIL_COLUMN dans les propriétés du script."
    );
  }

  var seen   = {};
  var emails = [];

  for (var i = 1; i < data.length; i++) {
    var email = String(data[i][emailCol]).trim().toLowerCase();
    if (isValidEmail_(email) && !seen[email]) {
      seen[email] = true;
      emails.push(email);
    }
  }

  return emails;
}

/**
 * Validation basique du format email.
 */
function isValidEmail_(email) {
  return /^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(email);
}

// ─── Lecture des emails existants depuis GitHub ───────────────────────────────

/**
 * Lit config/recipients.toml sur GitHub et retourne la liste des emails
 * déjà présents (ajouts manuels inclus). Retourne [] si le fichier est absent.
 */
function getExistingEmails_(url, token) {
  var response = UrlFetchApp.fetch(url + "?ref=" + CONFIG.GITHUB_BRANCH, {
    headers:            { "Authorization": "token " + token },
    muteHttpExceptions: true,
  });

  // Un échec de lecture ne doit PAS être confondu avec « liste vide ».
  // Sinon la fusion écraserait recipients.toml avec les seules adresses de la
  // Sheet, et la liste des désinscrits serait ignorée.
  var code = response.getResponseCode();
  if (code === 404) return [];                      // fichier absent : légitime
  if (code !== 200) {
    throw new Error(
      "Lecture de " + CONFIG.RECIPIENTS_PATH + " impossible (HTTP " + code + "). " +
      "Vérifier que GITHUB_TOKEN a accès à " + CONFIG.GITHUB_OWNER + "/" + CONFIG.GITHUB_REPO + ". " +
      "Synchronisation interrompue."
    );
  }

  var content = Utilities.newBlob(
    Utilities.base64Decode(JSON.parse(response.getContentText()).content.replace(/\n/g, ""))
  ).getDataAsString();

  // Extraction des emails depuis la ligne : emails = ["a@b.com", "c@d.com"]
  var match = content.match(/emails\s*=\s*\[([^\]]*)\]/);
  if (!match || !match[1].trim()) return [];

  var seen = {};
  return match[1].match(/"([^"]+)"/g)
    .map(function(e) { return e.replace(/"/g, "").trim().toLowerCase(); })
    .filter(function(e) {
      if (!isValidEmail_(e) || seen[e]) return false;
      seen[e] = true;
      return true;
    });
}

/**
 * Fusionne deux listes d'emails en supprimant les doublons.
 * Les emails de `base` apparaissent en premier (ordre préservé).
 */
function mergeEmails_(base, incoming) {
  var seen   = {};
  var result = [];
  base.concat(incoming).forEach(function(email) {
    var e = email.trim().toLowerCase();
    if (isValidEmail_(e) && !seen[e]) {
      seen[e] = true;
      result.push(e);
    }
  });
  return result;
}

// ─── Lecture des emails désinscrits depuis GitHub ─────────────────────────────

/**
 * Lit config/unsubscribed.toml sur GitHub.
 * Retourne {email: iso_timestamp} — compatible avec l'ancien format (timestamp vide).
 */
function getUnsubscribedEmailsWithTimestamps_(url, token) {
  var response = UrlFetchApp.fetch(url + "?ref=" + CONFIG.GITHUB_BRANCH, {
    headers:            { "Authorization": "token " + token },
    muteHttpExceptions: true,
  });

  // ⚠️ Le cas le plus dangereux : retourner {} sur un échec ferait croire que
  // personne ne s'est désabonné, et les désabonnés seraient RÉINSCRITS.
  var code = response.getResponseCode();
  if (code === 404) return {};                      // fichier absent : légitime
  if (code !== 200) {
    throw new Error(
      "Lecture de " + CONFIG.UNSUBSCRIBED_PATH + " impossible (HTTP " + code + "). " +
      "Poursuivre réinscrirait les désabonnés — synchronisation interrompue."
    );
  }

  var content = Utilities.newBlob(
    Utilities.base64Decode(JSON.parse(response.getContentText()).content.replace(/\n/g, ""))
  ).getDataAsString();

  var emailsMatch = content.match(/emails\s*=\s*\[([^\]]*)\]/);
  if (!emailsMatch || !emailsMatch[1].trim()) return {};

  var emails = emailsMatch[1].match(/"([^"]+)"/g)
    .map(function(e) { return e.replace(/"/g, "").trim().toLowerCase(); })
    .filter(isValidEmail_);

  var timestamps = [];
  var tsMatch = content.match(/timestamps\s*=\s*\[([^\]]*)\]/);
  if (tsMatch && tsMatch[1].trim()) {
    timestamps = tsMatch[1].match(/"([^"]+)"/g)
      .map(function(t) { return t.replace(/"/g, "").trim(); });
  }

  var result = {};
  emails.forEach(function(email, i) {
    result[email] = timestamps[i] || "";
  });
  return result;
}

/**
 * Parcourt la Sheet et retourne le dernier horodatage de soumission par email.
 * Retourne {email: Date}.
 */
function getLatestSubmissionByEmail_() {
  var sheetId = PropertiesService.getScriptProperties().getProperty("GOOGLE_SHEET_ID");
  if (!sheetId) return {};

  var sheet  = SpreadsheetApp.openById(sheetId).getActiveSheet();
  var data   = sheet.getDataRange().getValues();
  if (data.length < 2) return {};

  var header     = data[0];
  var emailCol   = header.indexOf(CONFIG.EMAIL_COLUMN);
  var tsCol      = header.indexOf(CONFIG.TIMESTAMP_COLUMN);
  if (emailCol === -1 || tsCol === -1) return {};

  var latest = {};
  for (var i = 1; i < data.length; i++) {
    var email = String(data[i][emailCol]).trim().toLowerCase();
    var ts    = data[i][tsCol];  // déjà un objet Date dans Google Sheets
    if (!isValidEmail_(email) || !ts) continue;
    var tsDate = (ts instanceof Date) ? ts : new Date(ts);
    if (!latest[email] || tsDate > latest[email]) {
      latest[email] = tsDate;
    }
  }
  return latest;
}

/**
 * Retire une liste d'emails de config/unsubscribed.toml via l'API GitHub.
 */
function removeFromUnsubscribed_(emailsToRemove, url, token) {
  var toRemoveSet = {};
  emailsToRemove.forEach(function(e) { toRemoveSet[e.toLowerCase()] = true; });

  // Lire le fichier actuel
  var response = UrlFetchApp.fetch(url + "?ref=" + CONFIG.GITHUB_BRANCH, {
    headers: { "Authorization": "token " + token },
    muteHttpExceptions: true,
  });
  if (response.getResponseCode() !== 200) return;

  var fileData   = JSON.parse(response.getContentText());
  var currentSha = fileData.sha;
  var content    = Utilities.newBlob(
    Utilities.base64Decode(fileData.content.replace(/\n/g, ""))
  ).getDataAsString();

  // Parser emails + timestamps
  var emailsMatch = content.match(/emails\s*=\s*\[([^\]]*)\]/);
  var emails = emailsMatch && emailsMatch[1].trim()
    ? emailsMatch[1].match(/"([^"]+)"/g).map(function(e) { return e.replace(/"/g, ""); })
    : [];

  var tsMatch = content.match(/timestamps\s*=\s*\[([^\]]*)\]/);
  var timestamps = tsMatch && tsMatch[1].trim()
    ? tsMatch[1].match(/"([^"]+)"/g).map(function(t) { return t.replace(/"/g, ""); })
    : [];

  // Filtrer les emails à supprimer
  var newEmails = [], newTimestamps = [];
  emails.forEach(function(email, i) {
    if (!toRemoveSet[email.toLowerCase()]) {
      newEmails.push(email);
      newTimestamps.push(timestamps[i] || "");
    }
  });

  // Reconstruire le TOML
  var emailsLine = newEmails.map(function(e) { return '"' + e + '"'; }).join(", ");
  var tsLine     = newTimestamps.map(function(t) { return '"' + t + '"'; }).join(", ");
  var newContent =
    "# Liste des adresses désinscrites de la newsletter\n" +
    "# Mis à jour automatiquement par auth_server via /unsubscribe\n\n" +
    "[unsubscribed]\n" +
    "emails     = [" + emailsLine + "]\n" +
    "timestamps = [" + tsLine + "]\n";

  // Écrire sur GitHub
  var encoded = Utilities.base64Encode(newContent, Utilities.Charset.UTF_8);
  var payload = {
    message: "chore: resubscribe " + emailsToRemove.join(", ") + " [skip ci]",
    content: encoded,
    branch:  CONFIG.GITHUB_BRANCH,
    sha:     currentSha,
  };
  UrlFetchApp.fetch(url, {
    method:             "put",
    contentType:        "application/json",
    headers:            { "Authorization": "token " + token },
    payload:            JSON.stringify(payload),
    muteHttpExceptions: true,
  });
}

/**
 * Envoie un email de notification au propriétaire pour chaque réinscription détectée.
 */
function sendResubscribeNotification_(emails) {
  try {
    var subject = "[Newsletter] Réinscription : " + emails.join(", ");
    var body =
      "Les adresses suivantes se sont réinscrites à la newsletter Daily News :\n\n" +
      emails.map(function(e) { return "  • " + e; }).join("\n") +
      "\n\nElle(s) ont été retirées de la liste des désinscrits et recevront à nouveau la newsletter.\n\n" +
      "Date : " + new Date().toISOString();
    MailApp.sendEmail(CONFIG.OWNER_EMAIL, subject, body);
    Logger.log("Notification de réinscription envoyée pour : " + emails.join(", "));
  } catch (err) {
    Logger.log("Erreur notification réinscription (non bloquant) : " + err.message);
  }
}

/**
 * Ajoute ou met à jour une colonne "Désinscrit" dans la Sheet
 * en marquant TRUE/FALSE selon la liste noire.
 */
function markUnsubscribedInSheet_(unsubscribedSet) {
  var sheetId = PropertiesService.getScriptProperties().getProperty("GOOGLE_SHEET_ID");
  if (!sheetId) return;

  var sheet  = SpreadsheetApp.openById(sheetId).getActiveSheet();
  var data   = sheet.getDataRange().getValues();
  if (data.length < 2) return;

  var header   = data[0];
  var emailCol = header.indexOf(CONFIG.EMAIL_COLUMN);
  if (emailCol === -1) return;

  // Trouver ou créer la colonne "Désinscrit"
  var unsubCol = header.indexOf(CONFIG.UNSUBSCRIBED_COLUMN);
  if (unsubCol === -1) {
    unsubCol = header.length;
    sheet.getRange(1, unsubCol + 1).setValue(CONFIG.UNSUBSCRIBED_COLUMN);
  }

  // Construire le tableau de valeurs en mémoire, puis écrire en un seul appel API
  var values = [];
  for (var i = 1; i < data.length; i++) {
    var email   = String(data[i][emailCol]).trim().toLowerCase();
    values.push([unsubscribedSet.hasOwnProperty(email) ? "TRUE" : "FALSE"]);
  }
  if (values.length > 0) {
    sheet.getRange(2, unsubCol + 1, values.length, 1).setValues(values);
  }

  Logger.log("Colonne '" + CONFIG.UNSUBSCRIBED_COLUMN + "' mise à jour dans la Sheet.");
}

// ─── Mise à jour du fichier TOML sur GitHub ───────────────────────────────────

/**
 * Met à jour config/recipients.toml via l'API GitHub.
 * Crée le fichier s'il n'existe pas, le met à jour sinon.
 */
function updateRecipientsFile_(emails, url, token) {
  // Récupérer le SHA actuel du fichier (requis pour la mise à jour)
  var currentSha = getCurrentSha_(url, token);

  // Construire le contenu TOML
  var tomlContent = buildToml_(emails);

  // Encoder en base64 (requis par l'API GitHub)
  var encoded = Utilities.base64Encode(tomlContent, Utilities.Charset.UTF_8);

  // Préparer le payload
  var payload = {
    message: "chore: sync recipients (" + emails.length + " emails) [skip ci]",
    content: encoded,
    branch:  CONFIG.GITHUB_BRANCH,
  };
  if (currentSha) {
    payload.sha = currentSha;  // Requis pour la mise à jour (absent pour création)
  }

  // Appel API GitHub
  var response = UrlFetchApp.fetch(url, {
    method:      "put",
    contentType: "application/json",
    headers:     { "Authorization": "token " + token },
    payload:     JSON.stringify(payload),
    muteHttpExceptions: true,
  });

  var code = response.getResponseCode();
  if (code !== 200 && code !== 201) {
    throw new Error(
      "GitHub API error " + code + " : " + response.getContentText()
    );
  }

  Logger.log("Fichier mis à jour : " + CONFIG.RECIPIENTS_PATH + " (HTTP " + code + ")");
}

/**
 * Récupère le SHA actuel du fichier sur la branche cible (null si absent).
 * Le paramètre ?ref= est requis pour cibler la bonne branche.
 * Note : getExistingEmails_ fait déjà un GET — getCurrentSha_ est appelé
 * séparément juste avant le PUT pour avoir le SHA à jour.
 */
function getCurrentSha_(url, token) {
  var response = UrlFetchApp.fetch(url + "?ref=" + CONFIG.GITHUB_BRANCH, {
    headers:            { "Authorization": "token " + token },
    muteHttpExceptions: true,
  });

  if (response.getResponseCode() === 200) {
    return JSON.parse(response.getContentText()).sha;
  }
  return null;  // Fichier absent → création
}

// ─── Helpers ──────────────────────────────────────────────────────────────────

/**
 * Construit le contenu TOML pour config/recipients.toml.
 */
function buildToml_(emails) {
  var lines = [
    "# Liste des destinataires de la newsletter",
    "# Mis à jour automatiquement par sync_recipients.gs",
    "# Dernière sync : " + new Date().toISOString(),
    "",
    "[recipients]",
    "emails = [" + emails.map(function(e) { return '"' + e + '"'; }).join(", ") + "]",
    "",
  ];
  return lines.join("\n");
}

/**
 * Construit l'URL de l'API GitHub pour un fichier du dépôt.
 */
function buildApiUrl_(filePath) {
  return (
    "https://api.github.com/repos/" +
    CONFIG.GITHUB_OWNER + "/" +
    CONFIG.GITHUB_REPO  + "/contents/" +
    filePath
  );
}

/**
 * Lit le GITHUB_TOKEN depuis les propriétés du script.
 * Lève une erreur explicite si absent.
 */
function getToken_() {
  var props = PropertiesService.getScriptProperties();
  var token = props.getProperty("GITHUB_TOKEN");
  if (!token) {
    throw new Error(
      "GITHUB_TOKEN manquant. " +
      "Aller dans Fichier → Propriétés du projet → Propriétés du script."
    );
  }
  return token;
}

// ─── Utilitaire : test manuel ─────────────────────────────────────────────────

/**
 * Fonction de test — à lancer manuellement depuis l'éditeur Apps Script
 * pour vérifier la configuration sans attendre une soumission de form.
 */
function testSync() {
  onFormSubmit(null);
}
