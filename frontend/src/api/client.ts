import axios from "axios";

// Access token is stored only in memory (never localStorage) to prevent XSS.
let _accessToken: string | null = null;

export function setAccessToken(token: string | null) {
  _accessToken = token;
}

export function getAccessToken(): string | null {
  return _accessToken;
}

export const api = axios.create({ baseURL: "/" });

// Attach access token to every request.
api.interceptors.request.use((cfg) => {
  if (_accessToken) {
    cfg.headers.Authorization = `Bearer ${_accessToken}`;
  }
  return cfg;
});

// On 401, try to silently refresh once.
let _isRefreshing = false;
let _refreshQueue: Array<(token: string | null) => void> = [];

api.interceptors.response.use(
  (r) => r,
  async (error) => {
    const original = error.config;
    if (error.response?.status === 401 && !original._retried) {
      original._retried = true;
      if (!_isRefreshing) {
        _isRefreshing = true;
        try {
          const res = await axios.post<{ access_token: string }>(
            "/api/auth/refresh-cookie",
            {},
            { withCredentials: true }
          );
          const newToken = res.data.access_token;
          setAccessToken(newToken);
          _refreshQueue.forEach((cb) => cb(newToken));
        } catch {
          setAccessToken(null);
          _refreshQueue.forEach((cb) => cb(null));
          window.location.href = "/login";
        } finally {
          _isRefreshing = false;
          _refreshQueue = [];
        }
      }
      return new Promise((resolve, reject) => {
        _refreshQueue.push((token) => {
          if (token) {
            original.headers.Authorization = `Bearer ${token}`;
            resolve(api(original));
          } else {
            reject(error);
          }
        });
      });
    }
    return Promise.reject(error);
  }
);
