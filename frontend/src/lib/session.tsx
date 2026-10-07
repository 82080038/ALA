"use client";

/**
 * Konteks identitas pengguna — header-based auth (JWT belum diimplementasi).
 * Identitas disimpan di localStorage dan dikirim via header X-* ke API.
 * Middleware tenant backend memvalidasi nilai role & tier.
 */
import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useState,
  type ReactNode,
} from "react";

export const ROLES = [
  "penyidik",
  "jaksa",
  "hakim",
  "admin_instansi",
  "super_admin",
] as const;
export const TIERS = ["free", "premium_l1", "premium_l2"] as const;

export type Role = (typeof ROLES)[number];
export type Tier = (typeof TIERS)[number];

export interface Identity {
  institutionId: string;
  userId: string;
  role: Role;
  tier: Tier;
}

const DEFAULT_IDENTITY: Identity = {
  institutionId: "",
  userId: "",
  role: "penyidik",
  tier: "free",
};

const STORAGE_KEY = "ala.identity";

interface SessionCtx {
  identity: Identity;
  setIdentity: (next: Partial<Identity>) => void;
  hydrated: boolean;
}

const Ctx = createContext<SessionCtx>({
  identity: DEFAULT_IDENTITY,
  setIdentity: () => {},
  hydrated: false,
});

export function SessionProvider({ children }: { children: ReactNode }) {
  const [identity, setIdentityState] = useState<Identity>(DEFAULT_IDENTITY);
  const [hydrated, setHydrated] = useState(false);

  useEffect(() => {
    try {
      const raw = localStorage.getItem(STORAGE_KEY);
      if (raw) setIdentityState({ ...DEFAULT_IDENTITY, ...JSON.parse(raw) });
    } catch {
      /* abaikan storage korup */
    }
    setHydrated(true);
  }, []);

  const setIdentity = useCallback((next: Partial<Identity>) => {
    setIdentityState((prev) => {
      const merged = { ...prev, ...next };
      try {
        localStorage.setItem(STORAGE_KEY, JSON.stringify(merged));
      } catch {
        /* abaikan */
      }
      return merged;
    });
  }, []);

  return (
    <Ctx.Provider value={{ identity, setIdentity, hydrated }}>
      {children}
    </Ctx.Provider>
  );
}

export function useSession() {
  return useContext(Ctx);
}

/** Bangun header tenant untuk request API. */
export function tenantHeaders(identity: Identity): Record<string, string> {
  const h: Record<string, string> = {
    "X-User-Role": identity.role,
    "X-Tier-Level": identity.tier,
  };
  if (identity.institutionId) h["X-Institution-ID"] = identity.institutionId;
  if (identity.userId) h["X-User-ID"] = identity.userId;
  return h;
}
