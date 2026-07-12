// Generic fetch helper. Contains no endpoint strings — customer and admin API
// modules layer their own paths on top, keeping their surfaces separate.
export async function request(path, { method = "GET", token, body, isForm } = {}) {
  const headers = {};
  if (token) headers["Authorization"] = `Bearer ${token}`;

  let payload;
  if (isForm) {
    payload = body; // FormData; browser sets the multipart boundary
  } else if (body !== undefined) {
    headers["Content-Type"] = "application/json";
    payload = JSON.stringify(body);
  }

  const res = await fetch(path, { method, headers, body: payload });
  const text = await res.text();
  let data = null;
  try {
    data = text ? JSON.parse(text) : null;
  } catch {
    data = text;
  }
  if (!res.ok) {
    const err = new Error("Request failed");
    err.status = res.status;
    err.data = data;
    throw err;
  }
  return data;
}

// Turn an API error into a human-friendly string.
export function errorMessage(err, fallback = "Something went wrong") {
  const d = err?.data?.detail;
  if (!d) return err?.message || fallback;
  if (typeof d === "string") return d;
  if (d.message) {
    if (Array.isArray(d.missing) && d.missing.length) {
      return `${d.message}: ${d.missing.join(", ")}`;
    }
    return d.message;
  }
  return fallback;
}
