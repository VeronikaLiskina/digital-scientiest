export const API_BASE_URL = import.meta.env.VITE_API_BASE_URL ?? "http://localhost:8000/api";
export const API_ROOT_URL = API_BASE_URL.replace(/\/api\/?$/, "");

type RequestOptions = RequestInit & {
  isFormData?: boolean;
};

export interface ApiErrorDetail {
  code?: string;
  title?: string;
  message: string;
  retryable?: boolean;
}

export class ApiError extends Error {
  readonly status: number;
  readonly code?: string;
  readonly title?: string;
  readonly retryable: boolean;

  constructor(status: number, detail: ApiErrorDetail) {
    super(detail.message);
    this.name = "ApiError";
    this.status = status;
    this.code = detail.code;
    this.title = detail.title;
    this.retryable = detail.retryable ?? false;
  }
}

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
    let detail: ApiErrorDetail = {
      message: `Ошибка запроса: ${response.status}`,
    };

    try {
      const errorData = await response.json();

      if (typeof errorData.detail === "string") {
        detail = { message: errorData.detail };
      } else if (Array.isArray(errorData.detail)) {
        detail = { message: JSON.stringify(errorData.detail) };
      } else if (
        errorData.detail &&
        typeof errorData.detail === "object"
      ) {
        detail = {
          code:
            typeof errorData.detail.code === "string"
              ? errorData.detail.code
              : undefined,
          title:
            typeof errorData.detail.title === "string"
              ? errorData.detail.title
              : undefined,
          message:
            typeof errorData.detail.message === "string"
              ? errorData.detail.message
              : `Ошибка запроса: ${response.status}`,
          retryable: errorData.detail.retryable === true,
        };
      }
    } catch {
      // backend вернул не JSON
    }

    throw new ApiError(response.status, detail);
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
