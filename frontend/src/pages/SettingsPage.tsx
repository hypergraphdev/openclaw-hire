import { useT, useLang, type Lang } from "../contexts/LanguageContext";

export function SettingsPage() {
  const t = useT();
  const { lang, setLang } = useLang();

  return (
    <div className="max-w-xl mx-auto">
      <h1 className="text-xl font-semibold text-white mb-6">{t("settings.title")}</h1>

      <div className="bg-gray-900 border border-gray-800 rounded-lg p-5">
        <h2 className="text-sm font-medium text-gray-300 mb-1">{t("settings.language")}</h2>
        <p className="text-xs text-gray-500 mb-4">{t("settings.languageDesc")}</p>

        <select
          value={lang}
          onChange={(e) => setLang(e.target.value as Lang)}
          className="bg-gray-800 border border-gray-700 rounded-md px-3 py-2 text-sm text-gray-200 focus:outline-none focus:border-gray-500"
        >
          <option value="en">{t("settings.langEn")}</option>
          <option value="zh">{t("settings.langZh")}</option>
        </select>
      </div>
    </div>
  );
}
