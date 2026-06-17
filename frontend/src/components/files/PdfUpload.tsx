import { useRef, useState } from "react";
import type { ChangeEvent } from "react";

import { sourceFilesApi } from "../../api/sourceFilesApi";
import type { SourceFile } from "../../types/entities";

interface PdfUploadProps {
  onUploaded?: (file: SourceFile) => void;
  onFileSelected?: (file: File | null) => void;
}

export function PdfUpload({ onUploaded, onFileSelected }: PdfUploadProps) {
  const inputRef = useRef<HTMLInputElement | null>(null);
  const [selectedFile, setSelectedFile] = useState<File | null>(null);
  const [isUploading, setIsUploading] = useState(false);
  const [error, setError] = useState("");

  const isDeferredUpload = Boolean(onFileSelected);

  function openFileDialog() {
    inputRef.current?.click();
  }

  function resetSelectedFile() {
    setSelectedFile(null);
    onFileSelected?.(null);

    if (inputRef.current) {
      inputRef.current.value = "";
    }
  }

  function handleFileChange(event: ChangeEvent<HTMLInputElement>) {
    const file = event.target.files?.[0] ?? null;

    if (!file) {
      resetSelectedFile();
      return;
    }

    if (file.type && file.type !== "application/pdf") {
      setError("Нужно выбрать PDF-файл");
      resetSelectedFile();
      return;
    }

    setError("");
    setSelectedFile(file);
    onFileSelected?.(file);
  }

  async function handleUpload() {
    if (!selectedFile) {
      openFileDialog();
      return;
    }

    if (!onUploaded) {
      return;
    }

    try {
      setIsUploading(true);
      setError("");

      const uploaded = await sourceFilesApi.upload(selectedFile);
      onUploaded(uploaded);
      resetSelectedFile();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Не удалось загрузить файл");
    } finally {
      setIsUploading(false);
    }
  }

  return (
    <div className="pdf-upload">
      <input
        ref={inputRef}
        className="pdf-upload__input"
        type="file"
        accept="application/pdf,.pdf"
        onChange={handleFileChange}
      />

      <div className="pdf-upload__content">
        <div>
          <p className="pdf-upload__title">Загрузка PDF</p>
          <p className="pdf-upload__hint">
            {selectedFile
              ? selectedFile.name
              : "Выберите файл с публикацией в формате PDF"}
          </p>
          {isDeferredUpload && selectedFile && (
            <p className="pdf-upload__hint">
              Файл будет загружен автоматически при создании публикации.
            </p>
          )}
        </div>

        <div className="pdf-upload__actions">
          <button className="button button_secondary" type="button" onClick={openFileDialog}>
            Выбрать PDF
          </button>

          {isDeferredUpload && selectedFile && (
            <button className="button button_secondary" type="button" onClick={resetSelectedFile}>
              Убрать файл
            </button>
          )}

          {!isDeferredUpload && (
            <button className="button" type="button" onClick={handleUpload} disabled={isUploading}>
              {isUploading ? "Загрузка..." : selectedFile ? "Загрузить PDF" : "Выбрать и загрузить"}
            </button>
          )}
        </div>
      </div>

      {error && <p className="error">{error}</p>}
    </div>
  );
}
