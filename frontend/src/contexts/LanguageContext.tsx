import { createContext, useCallback, useContext, useState, type ReactNode } from "react";
import { en } from "../i18n/en";
import { zh } from "../i18n/zh";

export type Lang = "en" | "zh";

const TRANSLATIONS: Record<Lang, Record<string, string>> = { en, zh };

interface LanguageState {
  lang: Lang;
  setLang: (lang: Lang) => void;
  t: (key: string, params?: Record<string, string | number>) => string;
}

const LanguageContext = createContext<LanguageState | null>(null);

function getInitialLang(): Lang {
  const stored = localStorage.getItem("lang");
  if (stored === "en" || stored === "zh") return stored;
  return navigator.language.startsWith("zh") ? "zh" : "en";
}

export function LanguageProvider({ children }: { children: ReactNode }) {
  const [lang, setLangState] = useState<Lang>(getInitialLang);

  const setLang = useCallback((newLang: Lang) => {
    localStorage.setItem("lang", newLang);
    setLangState(newLang);
  }, []);

  const t = useCallback(
    (key: string, params?: Record<string, string | number>) => {
      let text = TRANSLATIONS[lang][key] ?? TRANSLATIONS.en[key] ?? key;
      if (params) {
        for (const [k, v] of Object.entries(params)) {
          text = text.replace(`{${k}}`, String(v));
        }
      }
      return text;
    },
    [lang],
  );

  return (
    <LanguageContext.Provider value={{ lang, setLang, t }}>
      {children}
    </LanguageContext.Provider>
  );
}

export function useT() {
  const ctx = useContext(LanguageContext);
  if (!ctx) throw new Error("useT must be used inside LanguageProvider");
  return ctx.t;
}

export function useLang() {
  const ctx = useContext(LanguageContext);
  if (!ctx) throw new Error("useLang must be used inside LanguageProvider");
  return { lang: ctx.lang, setLang: ctx.setLang };
}
