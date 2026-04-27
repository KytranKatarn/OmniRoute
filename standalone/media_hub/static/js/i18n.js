/**
 * Lightweight i18n for Media Hub standalone.
 * window.MEDIA_HUB_LANG is injected by the Flask context processor.
 * Usage: window.t('nav.movies') → "Films" (fr) | "Películas" (es) | "Movies" (en)
 * Elements with data-i18n="key" are auto-translated on DOMContentLoaded.
 */
(function () {
  var STRINGS = {
    en: {
      "nav.dashboard": "Dashboard",
      "nav.movies":    "Movies",
      "nav.shows":     "Shows",
      "nav.requests":  "Requests",
      "nav.calendar":  "Calendar",
      "nav.stats":     "Stats",
      "nav.settings":  "Settings",
      "nav.discover":  "Discover",
      "nav.chat":      "Chat",
      "nav.profile":   "Profile",
      "nav.signout":   "Sign out",
      "lang.label":    "Language",
      "watchlist.add":    "Add to Watchlist",
      "watchlist.added":  "In Watchlist",
      "watchlist.remove": "Remove",
      "watchlist.empty":  "Your watchlist is empty.",
      "watchlist.title":  "Watchlist",
      "profile.title":    "Profile",
      "profile.account":  "Account",
      "profile.password": "Change Password",
      "profile.username": "Username",
      "profile.role":     "Role",
      "profile.admin":    "Administrator",
      "profile.member":   "Member",
      "btn.save":   "Save",
      "btn.update": "Update",
    },
    fr: {
      "nav.dashboard": "Tableau de bord",
      "nav.movies":    "Films",
      "nav.shows":     "Séries",
      "nav.requests":  "Demandes",
      "nav.calendar":  "Calendrier",
      "nav.stats":     "Statistiques",
      "nav.settings":  "Paramètres",
      "nav.discover":  "Découvrir",
      "nav.chat":      "Chat",
      "nav.profile":   "Profil",
      "nav.signout":   "Déconnexion",
      "lang.label":    "Langue",
      "watchlist.add":    "Ajouter à la liste",
      "watchlist.added":  "Dans la liste",
      "watchlist.remove": "Retirer",
      "watchlist.empty":  "Votre liste est vide.",
      "watchlist.title":  "Ma liste",
      "profile.title":    "Profil",
      "profile.account":  "Compte",
      "profile.password": "Changer le mot de passe",
      "profile.username": "Nom d'utilisateur",
      "profile.role":     "Rôle",
      "profile.admin":    "Administrateur",
      "profile.member":   "Membre",
      "btn.save":   "Enregistrer",
      "btn.update": "Mettre à jour",
    },
    es: {
      "nav.dashboard": "Panel",
      "nav.movies":    "Películas",
      "nav.shows":     "Series",
      "nav.requests":  "Solicitudes",
      "nav.calendar":  "Calendario",
      "nav.stats":     "Estadísticas",
      "nav.settings":  "Ajustes",
      "nav.discover":  "Descubrir",
      "nav.chat":      "Chat",
      "nav.profile":   "Perfil",
      "nav.signout":   "Cerrar sesión",
      "lang.label":    "Idioma",
      "watchlist.add":    "Añadir a la lista",
      "watchlist.added":  "En la lista",
      "watchlist.remove": "Quitar",
      "watchlist.empty":  "Tu lista está vacía.",
      "watchlist.title":  "Mi lista",
      "profile.title":    "Perfil",
      "profile.account":  "Cuenta",
      "profile.password": "Cambiar contraseña",
      "profile.username": "Usuario",
      "profile.role":     "Rol",
      "profile.admin":    "Administrador",
      "profile.member":   "Miembro",
      "btn.save":   "Guardar",
      "btn.update": "Actualizar",
    },
  };

  var lang = (window.MEDIA_HUB_LANG || "en").toLowerCase();
  var dict = STRINGS[lang] || STRINGS.en;

  window.t = function (key) {
    return dict[key] || STRINGS.en[key] || "";
  };

  document.addEventListener("DOMContentLoaded", function () {
    document.querySelectorAll("[data-i18n]").forEach(function (el) {
      var key = el.getAttribute("data-i18n");
      var val = window.t(key);
      if (val) el.textContent = val;
    });
  });
})();
