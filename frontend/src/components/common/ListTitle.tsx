interface ListTitleProps {
  title?: string;
  count: number;
}

export function ListTitle({ title = "Список", count }: ListTitleProps) {
  return (
    <h2 className="list-title">
      <span>{title}</span>
      <span className="list-title__count">{count}</span>
    </h2>
  );
}
