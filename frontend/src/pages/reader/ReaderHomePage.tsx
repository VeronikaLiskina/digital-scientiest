import { Link } from "react-router-dom";

export function ReaderHomePage() {
  return (
    <section className="reader-home-page">
      <div className="page-header">
        <div>
          <h1>Поиск научных материалов</h1>
          <p>
            Найдите публикацию, откройте исходный PDF или задайте вопрос по базе
            материалов.
          </p>
        </div>
      </div>

      <div className="reader-home-page__grid">
        <Link className="reader-action-card card" to="/publications">
          <div className="reader-action-card__content">
            <h2>Поиск публикаций</h2>
            <p>Поиск по названию, году, автору, теме, ключевым словам и DOI.</p>
          </div>
          <span className="reader-action-card__button">Перейти</span>
        </Link>

        <Link className="reader-action-card card" to="/assistant">
          <div className="reader-action-card__content">
            <h2>Ассистент по материалам</h2>
            <p>
              Задайте вопрос по базе публикаций и получите ответ с источниками.
            </p>
          </div>
          <span className="reader-action-card__button">Открыть</span>
        </Link>
      </div>
    </section>
  );
}
