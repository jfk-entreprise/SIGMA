part of 'order_bloc.dart';

sealed class OrderState {
  const OrderState();
}

final class OrderInitial extends OrderState {
  const OrderInitial();
}

final class OrderLoading extends OrderState {
  const OrderLoading();
}

final class DashboardLoaded extends OrderState {
  final List<LocalServiceOrder> pendingOrders;
  final List<LocalServiceOrder> todayPaidOrders;
  final int grossIncome;
  final int totalExpenses;
  final int totalCredits;

  const DashboardLoaded({
    required this.pendingOrders,
    required this.todayPaidOrders,
    required this.grossIncome,
    required this.totalExpenses,
    required this.totalCredits,
  });

  int get netIncome => grossIncome - totalExpenses - totalCredits;
}

final class BusinessItemsLoaded extends OrderState {
  final List<LocalBusinessItem> items;
  const BusinessItemsLoaded(this.items);
}

final class OrderActionSuccess extends OrderState {
  final String businessId;
  final String message;
  const OrderActionSuccess({required this.businessId, required this.message});
}

final class OrderError extends OrderState {
  final String message;
  const OrderError(this.message);
}
