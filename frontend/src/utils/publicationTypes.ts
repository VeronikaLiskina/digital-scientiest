export const publicationTypeOptions = [
  { value: "article", label: "Статья" },
  { value: "conference", label: "Материалы конференции" },
  { value: "report", label: "Отчет" },
  { value: "book", label: "Книга" },
  { value: "thesis", label: "Тезисы" },
];

export function getPublicationTypeLabel(value?: string | null) {
  if (!value) return "—";

  const option = publicationTypeOptions.find((item) => item.value === value);
  return option?.label ?? value;
}
