# CAHIER DES CHARGES COMPLET — KAZA

## ERP Mobile Intelligent pour Petits Commerces Africains

\---

# 1\. PRÉSENTATION GÉNÉRALE DU PROJET

## 1.1 Nom du projet

KAZA

\---

# 1.2 Vision du projet

KAZA est une application mobile ERP légère, modulaire et offline-first destinée aux petits commerces africains.

Le projet vise à permettre aux commerçants de :

* enregistrer leurs activités rapidement,
* suivre leurs revenus,
* contrôler les dépenses,
* gérer les crédits clients,
* visualiser leur chiffre d’affaire réel,
* superviser les opérations quotidiennes.

Le système doit être :

* extrêmement simple,
* rapide,
* visuel,
* compatible Android bas de gamme,
* utilisable par des employés peu technophiles.

Le produit ne doit jamais devenir un ERP complexe.

\---

# 1.3 Secteurs métiers ciblés

Le système est construit sur une architecture modulaire.

Le MVP démarre principalement avec :

## Module principal MVP

* Lavage auto

## Modules futurs

* Blanchisserie
* Pressing
* Maquis / Restaurant
* Salon de coiffure
* Garage
* Autres commerces terrain

\---

# 1.4 Philosophie UX

## Règles fondamentales

* 1 tap = 1 action utile
* Aucun écran inutile
* Navigation minimale
* Actions rapides prioritaires
* Gros boutons
* Très peu de texte
* Très peu de saisie clavier
* Temps moyen d’action inférieur à 4 secondes
* Design moderne et épuré
* Interface intuitive même sans formation

\---

# 2\. OBJECTIFS DU PRODUIT

## 2.1 Objectifs métier

Permettre aux commerces de :

* suivre les véhicules / services
* enregistrer les paiements
* gérer les crédits
* gérer les dépenses
* suivre les revenus journaliers
* produire des rapports automatiques
* superviser les employés
* contrôler le business à distance

\---

# 2.2 Objectifs techniques

* Fonctionnement offline-first
* Synchronisation robuste
* Compatibilité Android faible gamme
* Faible consommation mémoire
* Temps de réponse rapide
* Architecture modulaire
* UI dynamique selon le commerce

\---

# 3\. ARCHITECTURE GLOBALE DU PRODUIT

# 3.1 Architecture fonctionnelle

Le système est composé de :

## A. CORE SYSTEM

Modules communs à tous les commerces :

* Authentification
* Gestion utilisateurs
* Gestion commerces
* Synchronisation
* Notifications
* Rapports
* Facturation
* Configuration
* Abonnements

\---

## B. BUSINESS MODULES

Modules métier dynamiques.

Exemple :

### Wash Module

* véhicules
* types de lavage
* services complémentaires
* statuts véhicule

### Laundry Module

* vêtements
* statuts linge
* retrait
* tickets

\---

## C. DYNAMIC UI SYSTEM

Le système charge dynamiquement :

* composants UI
* icônes
* services
* workflows
* paramètres

selon le type de commerce choisi.

\---

# 4\. TECHNOLOGIES RECOMMANDÉES

# 4.1 Frontend Mobile

## Flutter

Pourquoi :

* performant
* animations fluides
* Android-first
* architecture scalable
* UI moderne
* compatible appareils faibles

\---

# 4.2 Backend API

## FastAPI

Pourquoi :

* rapide
* moderne
* async
* documentation automatique
* très bon pour mobile APIs

\---

# 4.3 Base de données cloud

## PostgreSQL

\---

# 4.4 Base de données locale mobile

## SQLite

\---

# 4.5 Cache et synchronisation

## Redis

\---

# 5\. STRUCTURE DES UTILISATEURS

# 5.1 Types de comptes

## OWNER (Propriétaire)

Le propriétaire du commerce.

### Permissions

* voir statistiques
* voir rapports
* modifier prix
* gérer utilisateurs
* supprimer opérations
* annuler factures
* voir historique actions
* gérer configuration
* gérer abonnement

\---

## MANAGER (Gérant)

Gestion quotidienne.

### Permissions

* enregistrer véhicules
* enregistrer paiements
* enregistrer crédits
* enregistrer dépenses
* voir dashboard
* voir liste attente
* appliquer réduction limitée

\---

## AGENT KAZA

Utilisateur interne KAZA.

### Permissions

* installer système
* configurer commerce
* assistance

\---

# 6\. PROCESSUS D’INSCRIPTION

# 6.1 Écran de lancement

## Objectifs

* chargement application
* vérification session
* synchronisation légère

\---

# 6.2 Écran connexion / inscription

## Première connexion

Le propriétaire :

* crée un compte
* saisit téléphone
* OTP
* informations personnelles

\---

## Connexion rapide

PIN CODE :

* 4 chiffres
* connexion ultra rapide

\---

# 7\. CONFIGURATION DU COMMERCE

# 7.1 Étape 1 — Choix du commerce

Le propriétaire choisit :

* Lavage auto
* Blanchisserie
* Pressing
* etc.

Un seul choix au MVP.

\---

# 7.2 Étape 2 — Informations commerce

Champs :

* nom commerce
* logo
* téléphone
* localisation
* devise

\---

# 7.3 Étape 3 — Sélection des items

Le système charge automatiquement les items correspondant au commerce.

Exemple lavage auto :

* 4x4
* Taxi
* Berline
* Moto
* Aspirateur
* Moteur
* Cire
* Parfum

Le propriétaire peut :

* activer
* désactiver
* modifier nom

\---

# 7.4 Étape 4 — Configuration

Chaque item activé :

* une catégorie
* un ordre affichage

\---

# 7.5 Étape 5 — Finalisation

Le système :

* génère la structure métier
* initialise la base locale
* prépare le dashboard
* synchronise le compte

\---

# 8\. DASHBOARD PRINCIPAL

# 8.1 Objectifs

Le dashboard doit :

* être ultra lisible
* permettre les actions rapides
* montrer les informations critiques

\---

# 8.2 Structure dashboard

## HEADER

Contient :

* logo commerce
* nom commerce
* notifications
* avatar utilisateur

\---

## KPI PRINCIPAL

### Grande card

CA NET JOURNALIER

Formule :

CA NET =
Total encaissé - (dépenses + crédits)

\---

## KPI SECONDAIRES

Cards secondaires :

* crédits
* dépenses
* véhicules terminés
* paiements

\---

## ACTIONS RAPIDES

### Grande Action Principale

🚗 Nouvelle voiture

### Actions secondaires

💸 Dépense
📄 Crédit

\---

## GRAPHIQUE

Graphique simple :

* évolution CA journalier

\---

## DERNIERS SERVICES

Liste des 3 à 5 derniers services.

Exemple :

|Véhicule|Type de lavage|Statut|Montant|
|-|-|-|-|
|4x4|Lavage complet|Terminé|6000|
|Taxi|Lavage simple|En attente|3000|

\---

## BOTTOM NAVIGATION

* Accueil
* Nouvelle voiture
* Liste attente
* Menu

\---

# 9\. WORKFLOW COMPLET D’UN VÉHICULE

# 9.1 Nouvelle voiture

Utilisateur clique :
🚗 Nouvelle voiture

\---

# 9.2 Sélection type véhicule

Choix :

* 4x4
* Berline
* Taxi
* Moto
* Bus

Chaque item affiche :

* icône
* nom

\---

# 9.3 Choix du type de lavage

Le système affiche les types de lavage disponibles.

Exemple :

* Lavage simple
* Lavage complet
* Lavage premium
* Lavage aspiré

Chaque type possède :

* nom
* prix

\---

# 9.4 Informations véhicule

Champs :

* immatriculation
* couleur

Optionnel :

* téléphone client
* nom client

\---

# 9.5 Services complémentaires

Exemple :

* moteur
* aspirateur
* cire
* parfum

Le système recalcule automatiquement le montant.

Exemple :

Lavage simple (4x4) = 4000
Moteur = 2000
Aspirateur = 1000

TOTAL = 7000

\---

# 9.6 Création commande

Le système crée :

* commande
* détails commande
* statut initial

\---

# 9.7 Statuts véhicule

## PENDING

En attente lavage

## PAID

Payé

## CANCELLED

Annulé

\---

# 9.8 Liste attente

L’écran affiche :

* type véhicule
* immatriculation
* heure arrivée
* montant
* statut

\---

# 9.9 Paiement

Modes paiement :

* espèces
* mobile money
* chèque
* crédit

\---

# 9.10 Facture

La facture affiche :

* logo commerce
* numéro facture
* date
* véhicule
* type lavage
* services
* réduction
* montant final
* mode paiement
* utilisateur

\---

# 10\. ÉCRAN DÉPENSES

# 10.1 Champs

* raison
* montant
* commentaire optionnel

Bouton :
ENREGISTRER

\---

# 10.2 Effets métier

Les dépenses réduisent automatiquement le CA NET.

\---

# 11\. ÉCRAN CRÉDITS

# 11.1 Champs

* nom client
* téléphone
* montant
* raison

\---

# 11.2 Effets métier

Les crédits impactent automatiquement le CA NET.

\---

# 12\. ÉCRAN STATISTIQUES

# 12.1 Objectifs

Seulement propriétaire. 

Permettre au propriétaire de :

* analyser activité
* contrôler revenus
* suivre évolution business

\---

# 12.2 KPI

Cards :

* CA jour
* dépenses
* crédits
* commandes
* véhicules

\---

# 12.3 Graphiques

## MVP

* évolution CA journalier

## Premium

* hebdomadaire
* mensuel
* top services
* heures rentables

\---

# 12.4 Historique détaillé

Liste paginée :

* opérations
* paiements
* crédits
* dépenses

\---

# 13\. DASHBOARD PROPRIÉTAIRE

# 13.1 Objectif

Contrôle business avancé.

\---

# 13.2 Éléments

* CA journalier
* CA hebdo
* CA mensuel
* crédits
* dépenses
* top services
* meilleur jour
* rapports récents

\---

# 14\. RAPPORTS

# 14.1 Rapport journalier

Contient :

* total véhicules
* total revenus
* dépenses
* crédits
* net final
* top services
* incidents

\---

# 14.2 Rapport hebdomadaire

Contient :

* évolution semaine
* comparaison jours
* top activités

\---

# 14.3 Rapport mensuel

Contient :

* chiffre mensuel
* dépenses mensuelles
* crédits mensuels
* tendances

\---

# 15\. SYSTÈME DE FACTURATION

# 15.1 Numéro facture

Format :

KAZA-2026-000001

\---

# 15.2 États facture

* draft
* pending
* paid
* credit
* cancelled

\---

# 15.3 Réductions

Chaque réduction doit journaliser :

* utilisateur
* date
* montant
* raison

\---

# 16\. ARCHITECTURE OFFLINE-FIRST

# 16.1 Principe fondamental

L’application doit fonctionner sans internet.

\---

# 16.2 Stockage local

SQLite contient :

* commandes
* paiements
* crédits
* dépenses
* utilisateurs
* configuration

\---

# 16.3 Synchronisation

Chaque action crée une queue locale.

Exemple :

{
"action": "CREATE\_ORDER",
"payload": {},
"sync\_status": "pending"
}

\---

# 16.4 Reconnexion internet

Le système :

* pousse les données
* récupère confirmations
* marque synchronisé

\---

# 16.5 Synchronisation idempotente

Obligatoire pour éviter :

* doublons
* pertes
* incohérences financières

\---

# 17\. DESIGN SYSTEM

# 17.1 Style général

* moderne
* minimaliste
* professionnel
* mobile-first
* très respirant

\---

# 17.2 Icônes

Style :

* fines
* simples
* outline
* personnalisées métier

\---

# 17.3 Couleurs

* couleur primaire forte
* beaucoup de blanc
* gris très léger
* couleurs statuts

\---

# 17.4 Composants UI réutilisables

## ActionCard

## StatsCard

## ItemCard

## WaitingCard

## PaymentModal

## ReportCard

## BottomNavigation

## StatusBadge

\---

# 18\. MODÈLE DE DONNÉES (DATABASE)

# 18.1 TABLE businesses

* id
* name
* type
* logo
* phone
* location
* owner\_id
* subscription\_plan
* created\_at

\---

# 18.2 TABLE users

* id
* business\_id
* fullname
* phone
* pin\_code
* role
* active
* created\_at

\---

# 18.3 TABLE item\_definitions

Base centrale des éléments métiers.

* id
* business\_type
* category
* label
* icon
* default\_price
* metadata\_json

\---

# 18.4 TABLE business\_items

Items activés par commerce.

* id
* business\_id
* item\_definition\_id
* custom\_name
* custom\_price
* active
* display\_order

\---

# 18.5 TABLE service\_orders

* id
* business\_id
* customer\_name
* customer\_phone
* vehicle\_number
* vehicle\_color
* wash\_type
* status
* subtotal
* discount
* total
* created\_by
* created\_at
* completed\_at

\---

# 18.6 TABLE service\_order\_items

* id
* order\_id
* business\_item\_id
* quantity
* unit\_price
* total\_price

\---

# 18.7 TABLE payments

* id
* order\_id
* payment\_method
* amount
* reference
* paid\_by
* paid\_at

\---

# 18.8 TABLE expenses

* id
* business\_id
* reason
* amount
* created\_by
* created\_at

\---

# 18.9 TABLE credits

* id
* business\_id
* customer\_name
* customer\_phone
* amount
* reason
* status
* created\_at

\---

# 18.10 TABLE daily\_reports

* id
* business\_id
* date
* gross\_income
* expenses
* credits
* net\_income
* total\_orders

\---

# 19\. API BACKEND

# 19.1 Modules API

* auth
* businesses
* users
* items
* orders
* payments
* credits
* expenses
* reports
* subscriptions

\---

# 19.2 Sécurité

* JWT
* OTP téléphone
* isolation stricte commerces
* logs actions
* permissions rôles

\---

# 20\. MODÈLE ÉCONOMIQUE

# 20.1 Gratuit

* ventes
* dashboard simple
* historique
* crédits
* dépenses
* rapport journalier

\---

# 20.2 Premium 2000 FCFA

* rapports hebdo
* rapports mensuels
* statistiques avancées
* sauvegarde cloud
* exports

\---

# 20.3 Premium Pro 5000 FCFA

* multi-appareils
* historique actions
* notifications et rapport intelligentes
* validation réductions
* supervision employés

\---

# 21\. KPIs PRODUIT

# 21.1 Adoption

* commerces installés
* commerces actifs/jour
* temps moyen opération
* commandes/jour

\---

# 21.2 Rétention

* rétention J7
* rétention J30
* ouverture rapports

\---

# 21.3 Monétisation

* conversion premium
* revenu moyen
* churn

\---

# 22\. RISQUES MAJEURS

* synchronisation offline
* surcharge UX
* lenteur application
* trop de fonctionnalités
* mauvaise adoption employés

\---

# 23\. OBJECTIF FINAL DU PRODUIT

Construire un système :

* simple
* rapide
* fiable
* visuel
* orienté terrain
* indispensable au propriétaire

Le produit doit aider les commerçants africains à :

* mieux contrôler leur argent,
* superviser leurs activités,
* réduire les pertes,
* prendre des décisions rapidement.

\---

# FIN DU CAHIER DES CHARGES

