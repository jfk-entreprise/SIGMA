import 'package:intl/intl.dart';

/// Utilitaires de formatage pour l'affichage des montants FCFA et des dates.
abstract final class Fmt {
  static final _fcfa = NumberFormat('#,##0', 'fr');
  static final _dt = DateFormat('HH:mm');
  static final _dayDt = DateFormat('dd/MM HH:mm');

  /// Formate un montant entier en FCFA — ex : "7 500 FCFA".
  static String fcfa(int amount) => '${_fcfa.format(amount)} FCFA';

  /// Formate l'heure d'un DateTime — ex : "09:30".
  static String time(DateTime dt) => _dt.format(dt);

  /// Formate date + heure courte — ex : "13/06 09:30".
  static String dateTime(DateTime dt) => _dayDt.format(dt);
}
