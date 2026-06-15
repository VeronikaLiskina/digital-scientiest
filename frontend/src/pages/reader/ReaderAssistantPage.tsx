export function ReaderAssistantPage() {
  return (
    <section className="reader-assistant-page">
      <div className="page-header">
        <div>
          <h1>Ассистент по материалам</h1>
          <p>
            Задайте вопрос по базе публикаций и получите ответ с указанием источников.
          </p>
        </div>
      </div>

      <section className="card reader-assistant">
        <textarea
          className="reader-assistant__textarea"
          placeholder="Например: Какие публикации есть по геохронологии Байкало-Муйского пояса?"
        />

        <button className="button" type="button">
          Задать вопрос
        </button>

        <div className="reader-assistant__answer">
          <p className="empty">
            Ответ ассистента появится здесь после подключения backend-логики.
          </p>
        </div>
      </section>
    </section>
  );
}