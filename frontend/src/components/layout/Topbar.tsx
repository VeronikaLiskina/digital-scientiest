import { useEffect, useRef, useState } from "react";
import { Link, useLocation } from "react-router-dom";

import { BookIcon, UserIcon } from "../icons/AppIcons";

interface TopbarProps {
  role?: string;
  homeTo?: string;
}

const appSections = [
  { key: "reader", label: "Учёный", to: "/" },
  { key: "admin", label: "Администратор", to: "/admin" },
] as const;

export function Topbar({ role = "Администратор", homeTo = "/" }: TopbarProps) {
  const [isMenuOpen, setIsMenuOpen] = useState(false);
  const location = useLocation();
  const switcherRef = useRef<HTMLDivElement>(null);
  const currentSection = location.pathname.startsWith("/admin") ? "admin" : "reader";
  const currentLabel = appSections.find((section) => section.key === currentSection)?.label ?? role;

  useEffect(() => {
    if (!isMenuOpen) {
      return;
    }

    function handleDocumentClick(event: MouseEvent) {
      if (!switcherRef.current?.contains(event.target as Node)) {
        setIsMenuOpen(false);
      }
    }

    function handleEscape(event: KeyboardEvent) {
      if (event.key === "Escape") {
        setIsMenuOpen(false);
      }
    }

    document.addEventListener("mousedown", handleDocumentClick);
    document.addEventListener("keydown", handleEscape);

    return () => {
      document.removeEventListener("mousedown", handleDocumentClick);
      document.removeEventListener("keydown", handleEscape);
    };
  }, [isMenuOpen]);

  return (
    <header className="topbar">
      <div className="topbar__container container container_center">
        <Link className="brand" to={homeTo}>
          <span className="brand__logo">
            <BookIcon />
          </span>
          <span className="brand__title">Цифровой учёный</span>
        </Link>

        <div className="profile-switcher" ref={switcherRef}>
          <button
            className={`profile-button${isMenuOpen ? " profile-button_open" : ""}`}
            type="button"
            aria-haspopup="menu"
            aria-expanded={isMenuOpen}
            onClick={() => setIsMenuOpen((isOpen) => !isOpen)}
          >
            <span className="profile-button__icon">
              <UserIcon />
            </span>
            <span className="profile-button__text">{currentLabel}</span>
            <span className="profile-button__chevron">⌄</span>
          </button>

          {isMenuOpen && (
            <div className="profile-menu" role="menu">
              {appSections.map((section) => {
                const isActive = section.key === currentSection;

                return (
                  <Link
                    key={section.key}
                    className={`profile-menu__item${isActive ? " profile-menu__item_active" : ""}`}
                    to={section.to}
                    role="menuitem"
                    aria-current={isActive ? "page" : undefined}
                    onClick={() => setIsMenuOpen(false)}
                  >
                    <span className="profile-menu__icon">
                      <UserIcon />
                    </span>
                    <span>{section.label}</span>
                  </Link>
                );
              })}
            </div>
          )}
        </div>
      </div>
    </header>
  );
}
