import type { DocumentChunk } from '../../api/types';

type Props = {
  chunks: DocumentChunk[];
};

export function DocumentChunksList({ chunks }: Props) {
  if (chunks.length === 0) {
    return <p className="muted">Текстовые фрагменты пока не созданы.</p>;
  }

  return (
    <div className="chunks-list">
      {chunks.map((chunk) => (
        <article className="chunk" key={chunk.id}>
          <div className="chunk__title">Фрагмент {chunk.chunk_index ?? chunk.id}</div>
          <p>{chunk.text}</p>
        </article>
      ))}
    </div>
  );
}
