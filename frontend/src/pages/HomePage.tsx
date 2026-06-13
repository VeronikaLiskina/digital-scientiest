import { Link } from "react-router-dom";

import { PageHeader } from "../components/common/PageHeader";
import {
  ClipboardIcon,
  DocumentIcon,
  FolderIcon,
  HashIcon,
  TagIcon,
  UserIcon,
} from "../components/icons/AppIcons";

const cards = [
  { title: "Публикации", icon: <DocumentIcon />, to: "/publications" },
  { title: "Файлы", icon: <FolderIcon />, to: "/files" },
  { title: "Авторы", icon: <UserIcon />, to: "/authors" },
  { title: "Темы", icon: <TagIcon />, to: "/topics" },
  { title: "Ключевые слова", icon: <HashIcon />, to: "/keywords" },
  { title: "Журнал обработки", icon: <ClipboardIcon />, to: "/processing-logs" },
];

export function HomePage() {
  return (
    <section className="home-page">
      <PageHeader title="Главная" description="Выберите раздел для работы" />

      <div className="home-page__grid">
        {cards.map((card) => (
          <Link key={card.title} className="home-card" to={card.to}>
            <span className="home-card__icon">{card.icon}</span>
            <span className="home-card__title">{card.title}</span>
          </Link>
        ))}
      </div>
    </section>
  );
}
