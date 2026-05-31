import 'dart:io';
import 'package:drift/drift.dart';
import 'package:drift/native.dart';
import 'package:path_provider/path_provider.dart';
import 'package:path/path.dart' as p;

part 'database.g.dart';

// ──────────────────────────────────────────────────────────────────
// TABLE : SyncQueue — File d'attente de synchronisation offline-first
// ──────────────────────────────────────────────────────────────────
class SyncQueue extends Table {
  /// UUID généré côté client (ex: uuid v4)
  TextColumn get id => text()();

  /// Verbe HTTP/domaine : CREATE | UPDATE | DELETE
  TextColumn get operation => text()();

  /// Entité cible : order | expense | credit | payment | …
  TextColumn get entity => text()();

  /// Payload JSON sérialisé (corps de la requête API)
  TextColumn get payload => text()();

  /// PENDING | SYNCING | DONE | FAILED
  TextColumn get status => text().withDefault(const Constant('PENDING'))();

  DateTimeColumn get createdAt =>
      dateTime().withDefault(currentDateAndTime)();

  IntColumn get retryCount => integer().withDefault(const Constant(0))();

  @override
  Set<Column> get primaryKey => {id};
}

// ──────────────────────────────────────────────────────────────────
// TABLE : LocalUsers
// ──────────────────────────────────────────────────────────────────
class LocalUsers extends Table {
  TextColumn get id => text()();
  TextColumn get phoneNumber => text()();
  TextColumn get fullName => text().nullable()();
  BoolColumn get isActive => boolean().withDefault(const Constant(true))();

  @override
  Set<Column> get primaryKey => {id};
}

// ──────────────────────────────────────────────────────────────────
// TABLE : LocalBusinesses
// ──────────────────────────────────────────────────────────────────
class LocalBusinesses extends Table {
  TextColumn get id => text()();
  TextColumn get name => text()();

  /// WASH | LAUNDRY | PRESSING
  TextColumn get businessType => text()();

  TextColumn get phone => text().nullable()();
  TextColumn get location => text().nullable()();
  BoolColumn get isActive => boolean().withDefault(const Constant(true))();

  /// FREE | PREMIUM | PREMIUM_PRO
  TextColumn get subscriptionPlan =>
      text().withDefault(const Constant('FREE'))();

  TextColumn get ownerId => text().references(LocalUsers, #id)();
  DateTimeColumn get createdAt =>
      dateTime().withDefault(currentDateAndTime)();

  @override
  Set<Column> get primaryKey => {id};
}

// ──────────────────────────────────────────────────────────────────
// TABLE : LocalBusinessItems — Catalogue de prestations
// ──────────────────────────────────────────────────────────────────
class LocalBusinessItems extends Table {
  TextColumn get id => text()();
  TextColumn get businessId => text().references(LocalBusinesses, #id)();
  TextColumn get name => text()();

  /// Montant en FCFA (entier, pas de virgule flottante)
  IntColumn get unitPrice => integer()();

  TextColumn get category => text().nullable()();
  BoolColumn get isActive => boolean().withDefault(const Constant(true))();

  @override
  Set<Column> get primaryKey => {id};
}

// ──────────────────────────────────────────────────────────────────
// TABLE : LocalServiceOrders — Commandes de service
// ──────────────────────────────────────────────────────────────────
class LocalServiceOrders extends Table {
  TextColumn get id => text()();
  TextColumn get businessId => text().references(LocalBusinesses, #id)();
  TextColumn get vehicleNumber => text()();

  /// PENDING | PAID | CANCELLED
  TextColumn get status => text().withDefault(const Constant('PENDING'))();

  /// Réduction en FCFA (toujours ≤ sous-total)
  IntColumn get discount => integer().withDefault(const Constant(0))();

  /// Total = sous-total - discount
  IntColumn get total => integer()();

  TextColumn get createdBy => text().references(LocalUsers, #id)();
  DateTimeColumn get createdAt =>
      dateTime().withDefault(currentDateAndTime)();
  DateTimeColumn get completedAt => dateTime().nullable()();

  @override
  Set<Column> get primaryKey => {id};
}

// ──────────────────────────────────────────────────────────────────
// TABLE : LocalServiceOrderItems — Lignes de commande
// ──────────────────────────────────────────────────────────────────
class LocalServiceOrderItems extends Table {
  TextColumn get id => text()();
  TextColumn get orderId =>
      text().references(LocalServiceOrders, #id)();
  TextColumn get businessItemId =>
      text().references(LocalBusinessItems, #id)();

  /// Snapshot du nom au moment de la commande
  TextColumn get name => text()();

  /// Snapshot du prix unitaire au moment de la commande
  IntColumn get unitPrice => integer()();

  IntColumn get quantity => integer()();

  /// unitPrice × quantity
  IntColumn get subtotal => integer()();

  @override
  Set<Column> get primaryKey => {id};
}

// ──────────────────────────────────────────────────────────────────
// TABLE : LocalExpenses — Dépenses opérationnelles
// ──────────────────────────────────────────────────────────────────
class LocalExpenses extends Table {
  TextColumn get id => text()();
  TextColumn get businessId => text().references(LocalBusinesses, #id)();
  TextColumn get reason => text()();
  IntColumn get amount => integer()();
  TextColumn get createdBy => text().references(LocalUsers, #id)();
  DateTimeColumn get createdAt =>
      dateTime().withDefault(currentDateAndTime)();

  @override
  Set<Column> get primaryKey => {id};
}

// ──────────────────────────────────────────────────────────────────
// TABLE : LocalCredits — Créances clients
// ──────────────────────────────────────────────────────────────────
class LocalCredits extends Table {
  TextColumn get id => text()();
  TextColumn get businessId => text().references(LocalBusinesses, #id)();
  TextColumn get customerName => text()();
  TextColumn get customerPhone => text().nullable()();
  IntColumn get amount => integer()();
  TextColumn get reason => text().nullable()();

  /// OUTSTANDING | REPAID
  TextColumn get status =>
      text().withDefault(const Constant('OUTSTANDING'))();

  TextColumn get createdBy => text().references(LocalUsers, #id)();
  DateTimeColumn get createdAt =>
      dateTime().withDefault(currentDateAndTime)();
  DateTimeColumn get repaidAt => dateTime().nullable()();

  /// UUID de l'utilisateur qui a marqué la créance remboursée (nullable)
  TextColumn get repaidBy => text().nullable()();

  @override
  Set<Column> get primaryKey => {id};
}

// ──────────────────────────────────────────────────────────────────
// BASE DE DONNÉES PRINCIPALE
// ──────────────────────────────────────────────────────────────────
@DriftDatabase(tables: [
  SyncQueue,
  LocalUsers,
  LocalBusinesses,
  LocalBusinessItems,
  LocalServiceOrders,
  LocalServiceOrderItems,
  LocalExpenses,
  LocalCredits,
])
class AppDatabase extends _$AppDatabase {
  AppDatabase() : super(_openConnection());

  /// Constructeur pour les tests unitaires (executor in-memory).
  AppDatabase.forTesting(super.executor);

  @override
  int get schemaVersion => 1;
}

LazyDatabase _openConnection() {
  return LazyDatabase(() async {
    final dbFolder = await getApplicationDocumentsDirectory();
    final file = File(p.join(dbFolder.path, 'sigma.db'));
    return NativeDatabase.createInBackground(file);
  });
}
