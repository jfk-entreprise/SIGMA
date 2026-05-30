# Rapport d'Audit de Sécurité & Robustesse — Module d'Authentification SIGMA

Ce document présente l'audit complet du système d'authentification développé pour le backend de **SIGMA**. L'analyse a porté sur la sécurité cryptographique, la gestion de la concurrence et de la robustesse, la protection contre la fraude (OTP, brute-force) et la pertinence de la suite de tests.

---

## 1. Sécurité & Cryptographie

### 🔑 Signature et validation des tokens JWT
* **Algorithme** : L'utilisation de `HS256` est conforme pour une signature à clé symétrique. Le fait de spécifier strictement `algorithms=[settings.JWT_ALGORITHM]` lors du décodage dans `decode_token` protège efficacement contre les attaques par confusion d'algorithme (ex: injection de tokens avec algorithme `none` ou substitution avec clés asymétriques).
* **Isolation des scopes** : Les tokens d'accès (`access`), de rafraîchissement (`refresh`) et d'inscription (`registration`) ont des payloads bien isolés et typés (vérifiés via `token_type` dans le payload), évitant qu'un jeton d'accès puisse être utilisé pour s'inscrire ou inversement.

### 🛡️ Gestion des variables d'environnement
* **Configuration** : Les secrets critiques (comme `JWT_SECRET_KEY`) ne sont pas écrits en dur dans le code source. Ils sont chargés dynamiquement depuis `.env` via `Pydantic Settings` (dans `app/config.py`).
* **Recommandation** : En production, il faudra s'assurer qu'un validateur bloque le démarrage si `JWT_SECRET_KEY` conserve sa valeur par défaut du fichier `.env.example`.

### ⚡ Hachage des mots de passe (Bcrypt)
* **Conformité** : L'utilisation de `passlib` avec le schéma `bcrypt` et 12 rounds est conforme aux standards actuels.
* **🚨 Vulnérabilité de déni de service (DoS) & Troncature** : 
  L'algorithme `bcrypt` tronque silencieusement les mots de passe de plus de 72 octets. Actuellement, le schéma `UserRegister` n'impose pas de limite supérieure (`max_length`) sur le champ `password`. Un attaquant pourrait envoyer un mot de passe de plusieurs mégaoctets, entraînant une surcharge CPU massive lors du hachage (DoS).
  * *Correction proposée* : Ajouter `max_length=72` sur les champs de mots de passe dans les schémas Pydantic.

* **🚨 Bug critique sur la protection contre l'énumération de comptes (Timing Attack)** :
  Dans `app/routers/auth.py` (ligne 463), en cas d'utilisateur inexistant, le code fait :
  ```python
  verify_password(body.password, "$2b$12$placeholder.hash.for.timing.attack.prevention")
  ```
  Le problème est que `"$2b$12$placeholder..."` n'est pas un hash bcrypt valide. Lors de l'exécution, `passlib` lève une exception `ValueError: invalid bcrypt hash`. Le serveur renvoie alors un statut **500 Internal Server Error** au lieu de l'erreur **401 Unauthorized** attendue. 
  Un attaquant peut donc instantanément énumérer les numéros de téléphone existants en comparant les réponses (500 pour inexistant, 401 pour existant avec mauvais mot de passe).
  * *Correction proposée* : Utiliser un hash bcrypt valide comme placeholder, par exemple :
    `"$2b$12$Lpy8yHn04s4e613K3l4P3e1B1G2H3I4J5K6L7M8N9O0P1Q2R3S4Tu"`

---

## 2. Robustesse & Gestion des Erreurs

### 🔌 Résilience de la base de données et de Redis
* **Redis hors-ligne** : Si Redis subit une déconnexion soudaine, les appels à `rc.store_otp`, `rc.get_otp`, etc., lèvent des exceptions `RedisError`. Ces exceptions ne sont pas capturées dans les routes de `app/routers/auth.py`, provoquant des erreurs 500 non gérées.
  * *Correction proposée* : Ajouter des blocs `try/except RedisError` dans les routes pour renvoyer un code d'erreur propre comme `503 Service Unavailable`.
* **Doublons concurrents (Race Conditions d'inscription)** :
  Le endpoint `/auth/register` effectue une vérification préalable :
  ```python
  existing_user = await _get_user_by_phone(body.phone_number)
  ```
  C'est un schéma classique de type TOCTOU (Time-of-Check to Time-of-Use). Si deux requêtes identiques sont exécutées de manière strictement parallèle, les deux passeront la validation et tenteront d'insérer l'utilisateur en base. 
  * *Correction proposée* : Lorsque SQLAlchemy sera intégré, il faudra impérativement intercepter les exceptions d'intégrité de la base de données (`IntegrityError` sur contrainte d'unicité) et renvoyer un code `409 Conflict`.

---

## 3. Protection Anti-Fraude (Rate Limiting)

### 🚨 Vulnérabilité critique de contournement du blocage OTP (Race Condition TOCTOU)
Le endpoint `/auth/otp/verify` vérifie le nombre de tentatives en interrogeant Redis *avant* de valider le code et d'incrémenter le compteur :
```python
# 1. Vérifier le nombre de tentatives
current_attempts_raw = await redis.get(attempts_key)
current_attempts = int(current_attempts_raw) if current_attempts_raw else 0
if current_attempts >= rc.MAX_OTP_ATTEMPTS:
    raise HTTPException(...)  # Bloqué

# 2. Vérifier l'OTP
if not _secrets.compare_digest(stored_otp, body.otp_code):
    # 3. Incrémenter après coup
    attempts = await rc.increment_otp_attempts(redis, phone_number)
```
Si un attaquant envoie de nombreuses requêtes de vérification en parallèle (par exemple 100 requêtes asynchrones simultanées), toutes liront `current_attempts` avant que l'incrément de la première requête ratée ne soit enregistré. L'attaquant peut ainsi tester des dizaines de codes en même temps et contourner la limite de 5 tentatives.
* *Correction proposée* : Incrémenter le compteur de tentatives **immédiatement** au début de la route de vérification via l'opération atomique de Redis, puis bloquer si la valeur retournée dépasse le maximum :
  ```python
  attempts = await rc.increment_otp_attempts(redis, phone_number)
  if attempts > rc.MAX_OTP_ATTEMPTS:
      raise HTTPException(
          status_code=status.HTTP_429_TOO_MANY_REQUESTS,
          detail="Trop de tentatives OTP. Veuillez en demander un nouveau."
      )
  ```

### ✉️ Absence de Rate Limiting sur la demande d'OTP et la Connexion
* **Demande d'OTP** : Il n'y a actuellement aucune restriction temporelle entre deux appels à `/auth/otp/request`. Un utilisateur malveillant pourrait appeler ce endpoint en boucle pour saturer le service de SMS ou épuiser le budget SMS de l'entreprise.
  * *Correction proposée* : Stocker un verrou temporaire dans Redis (ex: `sigma:otp_cooldown:{phone_number}`) d'une durée de 60 secondes pour bloquer les demandes trop rapprochées.
* **Connexion** : L'absence de rate limiting sur `/auth/login` expose l'application à des attaques de brute-force sur les mots de passe des utilisateurs.
  * *Correction proposée* : Mettre en place un limitateur de débit (Rate Limiter) applicatif (ex: via `slowapi` ou en utilisant un middleware Redis).

---

## 4. Qualité des Tests

* **Couverture** : La suite de tests dans `tests/test_auth.py` couvre bien les cas nominaux et d'erreur (format de téléphone, divergence de mot de passe, OTP expiré, trop de tentatives).
* **Fidélité des Mocks** :
  * Le mock de Redis dans `conftest.py` simule correctement l'API de base, mais il ne reproduit pas le comportement des expirations automatiques ni les comportements concurrents.
  * *Correction proposée* : Pour des tests plus rigoureux sans dépendance réseau externe, privilégier l'utilisation de `fakeredis` (qui simule fidèlement le comportement d'une base de données Redis en mémoire, y compris les TTL).

---

## Bilan de l'Audit

> [!WARNING]
> **Statut : FEU ORANGE (Modifications requises avant mise en production)**
> 
> Deux vulnérabilités critiques ont été identifiées :
> 1. **Timing Attack / Enumeration** : Le crash de `passlib` face au placeholder invalide révèle l'existence des utilisateurs.
> 2. **Bypass de Rate Limit OTP** : La faille de concurrence TOCTOU permet de brute-forcer les codes OTP en parallèle.

### Actions correctives prioritaires à mener :
1. Remplacer le hash placeholder par un hash bcrypt valide dans `/auth/login`.
2. Restructurer le flux de `/auth/otp/verify` pour incrémenter l'essai *avant* de valider le code.
3. Fixer une longueur maximale (`max_length=72`) pour le mot de passe dans les schémas d'inscription.
