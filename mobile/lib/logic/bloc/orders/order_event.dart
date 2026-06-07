part of 'order_bloc.dart';

sealed class OrderEvent {
  const OrderEvent();
}

/// Charge les KPIs du jour et la liste des commandes en attente.
final class OrderDashboardRequested extends OrderEvent {
  final String businessId;
  const OrderDashboardRequested(this.businessId);
}

/// Charge le catalogue d'articles du commerce (pour l'écran de saisie).
final class BusinessItemsRequested extends OrderEvent {
  final String businessId;
  const BusinessItemsRequested(this.businessId);
}

/// Crée une nouvelle commande localement et l'enfile dans la SyncQueue.
final class OrderCreateRequested extends OrderEvent {
  final String businessId;
  final String userId;
  final String reference; // plaque d'immatriculation ou numéro de ticket
  final List<OrderItemInput> items;
  final int discount;

  const OrderCreateRequested({
    required this.businessId,
    required this.userId,
    required this.reference,
    required this.items,
    this.discount = 0,
  });
}

/// Méthode de paiement disponible.
enum PaymentMethod { cash, mobileMoney }

/// Marque une commande comme payée et enfile l'action de paiement.
final class OrderPayRequested extends OrderEvent {
  final String orderId;
  final String businessId;
  final PaymentMethod method;

  const OrderPayRequested({
    required this.orderId,
    required this.businessId,
    required this.method,
  });
}

/// Annule une commande (mise à jour locale uniquement — pas de sync nécessaire
/// si la commande n'a jamais été synchronisée).
final class OrderCancelRequested extends OrderEvent {
  final String orderId;
  final String businessId;
  const OrderCancelRequested({required this.orderId, required this.businessId});
}

// ──────────────────────────────────────────────────────────────────
// DTO interne — ligne de commande en cours de saisie
// ──────────────────────────────────────────────────────────────────

class OrderItemInput {
  final String businessItemId;
  final String name;
  final int unitPrice;
  int quantity;

  OrderItemInput({
    required this.businessItemId,
    required this.name,
    required this.unitPrice,
    this.quantity = 1,
  });

  int get subtotal => unitPrice * quantity;
}
