import 'dart:convert';

import 'package:bloc_concurrency/bloc_concurrency.dart';
import 'package:drift/drift.dart';
import 'package:flutter_bloc/flutter_bloc.dart';

import 'package:sigma_app/core/utils/uuid_generator.dart';
import 'package:sigma_app/data/local/database.dart';
import 'package:sigma_app/data/local/sync_dao.dart';

part 'order_event.dart';
part 'order_state.dart';

class OrderBloc extends Bloc<OrderEvent, OrderState> {
  final AppDatabase _db;
  final SyncQueueDao _syncDao;

  OrderBloc({required AppDatabase db, required SyncQueueDao syncDao})
      : _db = db,
        _syncDao = syncDao,
        super(const OrderInitial()) {
    // sequential() : les requêtes dashboard ne s'entrelacent pas
    // si plusieurs événements arrivent en rafale (retour de navigation rapide).
    on<OrderDashboardRequested>(_onDashboardRequested,
        transformer: sequential());
    on<BusinessItemsRequested>(_onItemsRequested,
        transformer: sequential());
    on<OrderCreateRequested>(_onOrderCreate, transformer: sequential());
    on<OrderPayRequested>(_onOrderPay, transformer: sequential());
    on<OrderCancelRequested>(_onOrderCancel, transformer: sequential());
  }

  // ──────────────────────────────────────────────────────────────────
  // Dashboard
  // ──────────────────────────────────────────────────────────────────

  Future<void> _onDashboardRequested(
    OrderDashboardRequested event,
    Emitter<OrderState> emit,
  ) async {
    emit(const OrderLoading());
    try {
      final bId = event.businessId;
      final now = DateTime.now();
      final dayStart = DateTime(now.year, now.month, now.day);
      final dayEnd = dayStart.add(const Duration(days: 1));

      // Toutes les commandes du commerce (tri Dart pour éviter les conflits
      // sur la colonne nullable completedAt)
      final allOrders = await (_db.select(_db.localServiceOrders)
            ..where((t) => t.businessId.equals(bId)))
          .get();

      final pending = allOrders
          .where((o) => o.status == 'PENDING')
          .toList()
        ..sort((a, b) => b.createdAt.compareTo(a.createdAt));

      // PAID avec completedAt dans la journée — filtre Dart sur nullable
      final paid = allOrders.where((o) {
        final at = o.completedAt;
        return o.status == 'PAID' &&
            at != null &&
            !at.isBefore(dayStart) &&
            at.isBefore(dayEnd);
      }).toList();

      final gross = paid.fold(0, (s, o) => s + o.total);

      // Dépenses du jour
      final allExp = await (_db.select(_db.localExpenses)
            ..where((t) => t.businessId.equals(bId)))
          .get();
      final expenses = allExp
          .where((e) => !e.createdAt.isBefore(dayStart) && e.createdAt.isBefore(dayEnd))
          .fold(0, (s, e) => s + e.amount);

      // Crédits du jour
      final allCred = await (_db.select(_db.localCredits)
            ..where((t) => t.businessId.equals(bId)))
          .get();
      final credits = allCred
          .where((c) => !c.createdAt.isBefore(dayStart) && c.createdAt.isBefore(dayEnd))
          .fold(0, (s, c) => s + c.amount);

      emit(DashboardLoaded(
        pendingOrders: pending,
        todayPaidOrders: paid,
        grossIncome: gross,
        totalExpenses: expenses,
        totalCredits: credits,
      ));
    } catch (e) {
      emit(OrderError('Erreur de chargement: $e'));
    }
  }

  // ──────────────────────────────────────────────────────────────────
  // Catalogue d'articles
  // ──────────────────────────────────────────────────────────────────

  Future<void> _onItemsRequested(
    BusinessItemsRequested event,
    Emitter<OrderState> emit,
  ) async {
    emit(const OrderLoading());
    try {
      final items = await (_db.select(_db.localBusinessItems)
            ..where((t) =>
                t.businessId.equals(event.businessId) &
                t.isActive.equals(true))
            ..orderBy([(t) => OrderingTerm.asc(t.name)]))
          .get();
      emit(BusinessItemsLoaded(items));
    } catch (e) {
      emit(OrderError('Catalogue indisponible: $e'));
    }
  }

  // ──────────────────────────────────────────────────────────────────
  // Création de commande
  // ──────────────────────────────────────────────────────────────────

  Future<void> _onOrderCreate(
    OrderCreateRequested event,
    Emitter<OrderState> emit,
  ) async {
    emit(const OrderLoading());
    try {
      final orderId = generateUuid();
      final now = DateTime.now();
      final total =
          event.items.fold(0, (s, i) => s + i.subtotal) - event.discount;

      await _db.into(_db.localServiceOrders).insert(
            LocalServiceOrdersCompanion.insert(
              id: orderId,
              businessId: event.businessId,
              vehicleNumber: event.reference,
              discount: Value(event.discount),
              total: total,
              createdBy: event.userId,
              createdAt: Value(now),
            ),
          );

      for (final item in event.items) {
        await _db.into(_db.localServiceOrderItems).insert(
              LocalServiceOrderItemsCompanion.insert(
                id: generateUuid(),
                orderId: orderId,
                businessItemId: item.businessItemId,
                name: item.name,
                unitPrice: item.unitPrice,
                quantity: item.quantity,
                subtotal: item.subtotal,
              ),
            );
      }

      await _syncDao.addPendingAction(
        id: generateUuid(),
        operation: 'CREATE',
        entity: 'order',
        jsonPayload: jsonEncode({
          'id': orderId,
          'business_id': event.businessId,
          'vehicle_number': event.reference,
          'discount': event.discount,
          'items': event.items
              .map((i) => {
                    'business_item_id': i.businessItemId,
                    'name': i.name,
                    'unit_price': i.unitPrice,
                    'quantity': i.quantity,
                  })
              .toList(),
        }),
      );

      emit(OrderActionSuccess(
        businessId: event.businessId,
        message: 'Commande enregistrée.',
      ));
    } catch (e) {
      emit(OrderError('Création échouée: $e'));
    }
  }

  // ──────────────────────────────────────────────────────────────────
  // Paiement
  // ──────────────────────────────────────────────────────────────────

  Future<void> _onOrderPay(
    OrderPayRequested event,
    Emitter<OrderState> emit,
  ) async {
    emit(const OrderLoading());
    try {
      final now = DateTime.now();
      final order = await (_db.select(_db.localServiceOrders)
            ..where((t) => t.id.equals(event.orderId)))
          .getSingle();

      await (_db.update(_db.localServiceOrders)
            ..where((t) => t.id.equals(event.orderId)))
          .write(LocalServiceOrdersCompanion(
        status: const Value('PAID'),
        completedAt: Value(now),
      ));

      await _syncDao.addPendingAction(
        id: generateUuid(),
        operation: 'CREATE',
        entity: 'payment',
        jsonPayload: jsonEncode({
          'order_id': event.orderId,
          'amount': order.total,
          'payment_method':
              event.method == PaymentMethod.cash ? 'CASH' : 'MOBILE_MONEY',
        }),
      );

      emit(OrderActionSuccess(
        businessId: event.businessId,
        message: 'Paiement enregistré.',
      ));
    } catch (e) {
      emit(OrderError('Paiement échoué: $e'));
    }
  }

  // ──────────────────────────────────────────────────────────────────
  // Annulation
  // ──────────────────────────────────────────────────────────────────

  Future<void> _onOrderCancel(
    OrderCancelRequested event,
    Emitter<OrderState> emit,
  ) async {
    emit(const OrderLoading());
    try {
      await (_db.update(_db.localServiceOrders)
            ..where((t) => t.id.equals(event.orderId)))
          .write(const LocalServiceOrdersCompanion(
        status: Value('CANCELLED'),
      ));

      emit(OrderActionSuccess(
        businessId: event.businessId,
        message: 'Commande annulée.',
      ));
    } catch (e) {
      emit(OrderError('Annulation échouée: $e'));
    }
  }
}
