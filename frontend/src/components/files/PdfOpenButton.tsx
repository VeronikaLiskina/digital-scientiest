import { getFileDownloadUrl } from '../../api/client';

type Props = {
  sourceFileId?: number | null;
};

export function PdfOpenButton({ sourceFileId }: Props) {
  if (!sourceFileId) {
    return <span className="muted">PDF не привязан.</span>;
  }

  return (
    <a className="button button_secondary" href={getFileDownloadUrl(sourceFileId)} target="_blank" rel="noreferrer">
      Открыть PDF
    </a>
  );
}
