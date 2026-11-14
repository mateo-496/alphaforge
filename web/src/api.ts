const API_URL = import.meta.env.VITE_API_URL as string;

export async function runChain(body: unknown) {
  const r = await fetch(`${API_URL}/run`, { method: "POST", body: JSON.stringify(body) });
  return r.json(); // shape: ChainResult (core/schemas.py)
}
