import { Link } from "react-router-dom";

import { BookIcon, UserIcon } from "../icons/AppIcons";

interface TopbarProps {
  role?: string;
  homeTo?: string;
}

export function Topbar({ role = "Администратор", homeTo = "/" }: TopbarProps) {
  return (
    <header className="topbar">
      <div className="topbar__container container container_center">
        <Link className="brand" to={homeTo}>
          <span className="brand__logo">
            <BookIcon />
          </span>
          <span className="brand__title">Цифровой учёный</span>
        </Link>

        <button className="profile-button" type="button">
          <span className="profile-button__icon">
            <UserIcon />
          </span>
          <span className="profile-button__text">{role}</span>
          <span className="profile-button__chevron">⌄</span>
        </button>
      </div>
    </header>
  );
}
