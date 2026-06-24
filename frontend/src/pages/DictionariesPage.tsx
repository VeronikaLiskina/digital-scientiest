import { FormEvent, useEffect, useMemo, useState } from "react";

import { authorsApi } from "../api/authorsApi";
import { keywordsApi } from "../api/keywordsApi";
import { topicsApi } from "../api/topicsApi";

type DictionaryType = "authors" | "topics" | "keywords";

type Props = {
  type: DictionaryType;
};

type DictionaryItem = {
  id: number;
  title: string;
  subtitle?: string | null;
};

type DictionaryFormState = {
  full_name: string;
  organization: string;
  name: string;
  description: string;
};

const initialForm: DictionaryFormState = {
  full_name: "",
  organization: "",
  name: "",
  description: "",
};

function getDictionaryTitle(type: DictionaryType) {
  if (type === "authors") return "РђРІС‚РѕСЂС‹";
  if (type === "topics") return "РўРµРјС‹";
  return "РљР»СЋС‡РµРІС‹Рµ СЃР»РѕРІР°";
}

function getDictionaryDescription(type: DictionaryType) {
  if (type === "authors") return "Р”РѕР±Р°РІР»СЏР№С‚Рµ Р°РІС‚РѕСЂРѕРІ, С‡С‚РѕР±С‹ РїРѕС‚РѕРј РІС‹Р±РёСЂР°С‚СЊ РёС… РІ РєР°СЂС‚РѕС‡РєРµ РїСѓР±Р»РёРєР°С†РёРё.";
  if (type === "topics") return "Р”РѕР±Р°РІР»СЏР№С‚Рµ С‚РµРјС‹ РґР»СЏ РіСЂСѓРїРїРёСЂРѕРІРєРё Рё С„РёР»СЊС‚СЂР°С†РёРё РїСѓР±Р»РёРєР°С†РёР№.";
  return "Р”РѕР±Р°РІР»СЏР№С‚Рµ РєР»СЋС‡РµРІС‹Рµ СЃР»РѕРІР° РґР»СЏ РїРѕРёСЃРєР° Рё РѕРїРёСЃР°РЅРёСЏ РїСѓР±Р»РёРєР°С†РёР№.";
}

function getCreateButtonText(type: DictionaryType) {
  if (type === "authors") return "Р”РѕР±Р°РІРёС‚СЊ Р°РІС‚РѕСЂР°";
  if (type === "topics") return "Р”РѕР±Р°РІРёС‚СЊ С‚РµРјСѓ";
  return "Р”РѕР±Р°РІРёС‚СЊ РєР»СЋС‡РµРІРѕРµ СЃР»РѕРІРѕ";
}

export function DictionariesPage({ type }: Props) {
  const [items, setItems] = useState<DictionaryItem[]>([]);
  const [form, setForm] = useState<DictionaryFormState>(initialForm);
  const [error, setError] = useState<string | null>(null);
  const [success, setSuccess] = useState<string | null>(null);
  const [isLoading, setIsLoading] = useState(true);
  const [isSaving, setIsSaving] = useState(false);

  const title = useMemo(() => getDictionaryTitle(type), [type]);
  const description = useMemo(() => getDictionaryDescription(type), [type]);

  function updateForm<K extends keyof DictionaryFormState>(key: K, value: DictionaryFormState[K]) {
    setForm((prev) => ({ ...prev, [key]: value }));
  }

  function mapAuthors() {
    return authorsApi.getAll().then((data) =>
      data.map((item) => ({
        id: item.id,
        title: item.full_name,
        subtitle: item.organization,
      })),
    );
  }

  function mapTopics() {
    return topicsApi.getAll().then((data) =>
      data.map((item) => ({
        id: item.id,
        title: item.name,
        subtitle: item.description,
      })),
    );
  }

  function mapKeywords() {
    return keywordsApi.getAll().then((data) =>
      data.map((item) => ({
        id: item.id,
        title: item.name,
      })),
    );
  }

  async function loadItems() {
    setIsLoading(true);
    setError(null);

    try {
      const data =
        type === "authors" ? await mapAuthors() : type === "topics" ? await mapTopics() : await mapKeywords();

      setItems(data);
    } catch (e) {
      setError(e instanceof Error ? e.message : "РќРµ СѓРґР°Р»РѕСЃСЊ Р·Р°РіСЂСѓР·РёС‚СЊ СЃРїСЂР°РІРѕС‡РЅРёРє.");
    } finally {
      setIsLoading(false);
    }
  }

  useEffect(() => {
    setForm(initialForm);
    setSuccess(null);
    void loadItems();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [type]);

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setError(null);
    setSuccess(null);

    try {
      setIsSaving(true);

      if (type === "authors") {
        const fullName = form.full_name.trim();
        if (!fullName) {
          setError("РЈРєР°Р¶РёС‚Рµ Р¤РРћ Р°РІС‚РѕСЂР°.");
          return;
        }

        await authorsApi.create({
          full_name: fullName,
          organization: form.organization.trim(),
        });
        setSuccess("РђРІС‚РѕСЂ РґРѕР±Р°РІР»РµРЅ.");
      }

      if (type === "topics") {
        const name = form.name.trim();
        if (!name) {
          setError("РЈРєР°Р¶РёС‚Рµ РЅР°Р·РІР°РЅРёРµ С‚РµРјС‹.");
          return;
        }

        await topicsApi.create({
          name,
          description: form.description.trim(),
        });
        setSuccess("РўРµРјР° РґРѕР±Р°РІР»РµРЅР°.");
      }

      if (type === "keywords") {
        const name = form.name.trim();
        if (!name) {
          setError("РЈРєР°Р¶РёС‚Рµ РєР»СЋС‡РµРІРѕРµ СЃР»РѕРІРѕ.");
          return;
        }

        await keywordsApi.create({ name });
        setSuccess("РљР»СЋС‡РµРІРѕРµ СЃР»РѕРІРѕ РґРѕР±Р°РІР»РµРЅРѕ.");
      }

      setForm(initialForm);
      await loadItems();
    } catch (e) {
      setError(e instanceof Error ? e.message : "РќРµ СѓРґР°Р»РѕСЃСЊ СЃРѕС…СЂР°РЅРёС‚СЊ Р·Р°РїРёСЃСЊ.");
    } finally {
      setIsSaving(false);
    }
  }

  return (
    <section className={`dictionary-page dictionary-page_type_${type}`}>
      <div className="dictionary-page__header page-header">
        <div>
          <h1>{title}</h1>
          <p>{description}</p>
        </div>
      </div>

      <div className="dictionary-page__content">
        <form className="dictionary-form card" onSubmit={handleSubmit}>
          <h2 className="dictionary-form__title">РќРѕРІР°СЏ Р·Р°РїРёСЃСЊ</h2>

          {type === "authors" && (
            <>
              <label className="dictionary-form__field">
                <span className="dictionary-form__label">Р¤РРћ Р°РІС‚РѕСЂР° *</span>
                <input
                  className="dictionary-form__control"
                  value={form.full_name}
                  placeholder="РРІР°РЅРѕРІ Р. Р."
                  onChange={(event) => updateForm("full_name", event.target.value)}
                />
              </label>

              <label className="dictionary-form__field">
                <span className="dictionary-form__label">РћСЂРіР°РЅРёР·Р°С†РёСЏ</span>
                <input
                  className="dictionary-form__control"
                  value={form.organization}
                  placeholder="РРЅСЃС‚РёС‚СѓС‚ Р·РµРјРЅРѕР№ РєРѕСЂС‹ РЎРћ Р РђРќ"
                  onChange={(event) => updateForm("organization", event.target.value)}
                />
              </label>
            </>
          )}

          {type === "topics" && (
            <>
              <label className="dictionary-form__field">
                <span className="dictionary-form__label">РќР°Р·РІР°РЅРёРµ С‚РµРјС‹ *</span>
                <input
                  className="dictionary-form__control"
                  value={form.name}
                  placeholder="Р‘Р°Р№РєР°Р»"
                  onChange={(event) => updateForm("name", event.target.value)}
                />
              </label>

              <label className="dictionary-form__field">
                <span className="dictionary-form__label">РћРїРёСЃР°РЅРёРµ</span>
                <textarea
                  className="dictionary-form__control dictionary-form__control_textarea"
                  value={form.description}
                  placeholder="РџСѓР±Р»РёРєР°С†РёРё, СЃРІСЏР·Р°РЅРЅС‹Рµ СЃ Р‘Р°Р№РєР°Р»СЊСЃРєРёРј СЂРµРіРёРѕРЅРѕРј"
                  onChange={(event) => updateForm("description", event.target.value)}
                />
              </label>
            </>
          )}

          {type === "keywords" && (
            <label className="dictionary-form__field">
              <span className="dictionary-form__label">РљР»СЋС‡РµРІРѕРµ СЃР»РѕРІРѕ *</span>
              <input
                className="dictionary-form__control"
                value={form.name}
                placeholder="РіРµРѕР»РѕРіРёСЏ"
                onChange={(event) => updateForm("name", event.target.value)}
              />
            </label>
          )}

          {error && <p className="dictionary-form__message error">{error}</p>}
          {success && <p className="dictionary-form__message success">{success}</p>}

          <button className="dictionary-form__button button" type="submit" disabled={isSaving}>
            {isSaving ? "РЎРѕС…СЂР°РЅСЏРµРј..." : getCreateButtonText(type)}
          </button>
        </form>

        <div className="dictionary-list">
          <div className="dictionary-list__header">
            <h2 className="dictionary-list__title">РЎРїРёСЃРѕРє</h2>
            <span className="dictionary-list__count">{items.length}</span>
          </div>

          {isLoading && <p className="dictionary-list__empty muted">Р—Р°РіСЂСѓР·РєР°...</p>}

          {!isLoading && items.length === 0 && (
            <p className="dictionary-list__empty muted">Р—Р°РїРёСЃРµР№ РїРѕРєР° РЅРµС‚. Р”РѕР±Р°РІСЊС‚Рµ РїРµСЂРІСѓСЋ Р·Р°РїРёСЃСЊ С‡РµСЂРµР· С„РѕСЂРјСѓ.</p>
          )}

          {!isLoading && items.length > 0 && (
            <div className="dictionary-list__items">
              {items.map((item) => (
                <article className="dictionary-list__item card" key={item.id}>
                  <h3 className="dictionary-list__item-title">{item.title}</h3>
                  {item.subtitle && <p className="dictionary-list__item-subtitle muted">{item.subtitle}</p>}
                </article>
              ))}
            </div>
          )}
        </div>
      </div>
    </section>
  );
}

