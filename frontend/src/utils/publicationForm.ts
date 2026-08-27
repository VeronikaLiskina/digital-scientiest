export function uniqueIds(ids: number[]) {
  return Array.from(new Set(ids));
}


export function mergeIds(current: number[], incoming?: number[]) {
  return uniqueIds([...current, ...(incoming ?? [])]);
}


export function mergeById<T extends { id: number }>(current: T[], incoming: T[]) {
  const byId = new Map<number, T>();
  [...current, ...incoming].forEach((item) => byId.set(item.id, item));
  return Array.from(byId.values());
}


export function getMatchedIds(
  ids?: number[],
  matches?: { id: number }[],
) {
  return ids?.length ? ids : (matches?.map((item) => item.id) ?? []);
}


export function getNewNames(newNames?: string[], fallbackNames?: string[]) {
  // The fallback keeps compatibility with metadata produced by older backends.
  return newNames !== undefined ? newNames : (fallbackNames ?? []);
}


export function mergeNames(current: string, incoming?: string[]) {
  const values = [
    ...current
      .split(/[;,\n]/)
      .map((item) => item.trim())
      .filter(Boolean),
    ...(incoming ?? []),
  ];
  return Array.from(new Set(values)).join("\n");
}


export function pickExtractedValue(
  current: string,
  incoming: string | number | null | undefined,
  emptyOnly: boolean,
) {
  if (incoming === null || incoming === undefined || incoming === "") {
    return current;
  }
  if (emptyOnly && current.trim()) {
    return current;
  }
  return String(incoming);
}
