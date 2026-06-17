import { useState } from "react";

interface QuickCreateFieldProps {
  label: string;
  placeholder: string;
  buttonText: string;
  onCreate: (value: string) => Promise<void>;
}

export function QuickCreateField({
  label,
  placeholder,
  buttonText,
  onCreate,
}: QuickCreateFieldProps) {
  const [value, setValue] = useState("");
  const [error, setError] = useState("");
  const [isSaving, setIsSaving] = useState(false);

  async function handleCreate() {
    const trimmedValue = value.trim();

    if (!trimmedValue) {
      setError(label);
      return;
    }

    try {
      setIsSaving(true);
      setError("");
      await onCreate(trimmedValue);
      setValue("");
    } catch (err) {
      setError(err instanceof Error ? err.message : "Не удалось создать запись");
    } finally {
      setIsSaving(false);
    }
  }

  return (
    <div className="quick-create">
      <input
        value={value}
        placeholder={placeholder}
        onChange={(event) => setValue(event.target.value)}
      />
      <button
        className="button button_secondary"
        type="button"
        onClick={handleCreate}
        disabled={isSaving}
      >
        {isSaving ? "Добавляем..." : buttonText}
      </button>
      {error && <p className="error quick-create__error">{error}</p>}
    </div>
  );
}
