part of 'auth_bloc.dart';

sealed class AuthEvent {
  const AuthEvent();
}

/// Déclenché au démarrage de l'app — vérifie si un PIN est déjà configuré.
final class AuthStarted extends AuthEvent {
  const AuthStarted();
}

/// L'utilisateur appuie sur une touche numérique du numpad.
final class AuthDigitPressed extends AuthEvent {
  final String digit;
  const AuthDigitPressed(this.digit);
}

/// L'utilisateur appuie sur la touche effacement arrière.
final class AuthBackspacePressed extends AuthEvent {
  const AuthBackspacePressed();
}

/// Déclenché par le timer interne de décompte du verrouillage.
final class _AuthLockoutTick extends AuthEvent {
  const _AuthLockoutTick();
}

/// Déclenché par le lifecycle observer quand l'app revient au premier plan
/// après un délai d'inactivité — force le re-verrouillage.
final class AuthLockRequested extends AuthEvent {
  const AuthLockRequested();
}
