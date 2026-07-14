export const API_BASE_URL = import.meta.env.VITE_API_BASE_URL ?? "http://localhost:8000/api";
export const API_ROOT_URL = API_BASE_URL.replace(/\/api\/?$/, "");

type RequestOptions = RequestInit & {
  isFormData?: boolean;
};

async function request<T>(
  path: string,
  options: RequestOptions = {},
  baseUrl = API_BASE_URL,
): Promise<T> {
  const { isFormData, headers, ...rest } = options;

  const response = await fetch(`${baseUrl}${path}`, {
    ...rest,
    headers: isFormData
      ? headers
      : {
          "Content-Type": "application/json",
          ...headers,
        },
  });

  if (!response.ok) {
    let message = `Ошибка запроса: ${response.status}`;

    try {
      const errorData = await response.json();

      if (typeof errorData.detail === "string") {
        message = errorData.detail;
      } else if (errorData.detail) {
        message = JSON.stringify(errorData.detail);
      }
    } catch {
      // backend вернул не JSON
    }

    throw new Error(message);
  }

  if (response.status === 204) {
    return undefined as T;
  }

  return response.json() as Promise<T>;
}

export const apiClient = {
  get: <T>(path: string) => request<T>(path),
  post: <T>(path: string, body: unknown) =>
    request<T>(path, {
      method: "POST",
      body: JSON.stringify(body),
    }),
  patch: <T>(path: string, body: unknown) =>
    request<T>(path, {
      method: "PATCH",
      body: JSON.stringify(body),
    }),
  delete: <T>(path: string) =>
    request<T>(path, {
      method: "DELETE",
    }),
  postForm: <T>(path: string, body: FormData) =>
    request<T>(path, {
      method: "POST",
      body,
      isFormData: true,
    }),
};

export const rootApiClient = {
  get: <T>(path: string) => request<T>(path, {}, API_ROOT_URL),
  post: <T>(path: string, body: unknown) =>
    request<T>(
      path,
      {
        method: "POST",
        body: JSON.stringify(body),
      },
      API_ROOT_URL,
    ),
  delete: <T>(path: string) =>
    request<T>(
      path,
      {
        method: "DELETE",
      },
      API_ROOT_URL,
    ),
};
