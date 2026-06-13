interface StatusBadgeProps {
  value: string;
}

const statusLabels: Record<string, string> = {
  draft: "Черновик",
  new: "Новый",
  processed: "Обработан",
  processing: "В обработке",
  success: "Успешно",
  error: "Ошибка",
  review: "На проверке",
  pending: "Ожидает",
};

export function StatusBadge({ value }: StatusBadgeProps) {
  const label = statusLabels[value] ?? value;

  return <span className={`status status_${value}`}>{label}</span>;
}
