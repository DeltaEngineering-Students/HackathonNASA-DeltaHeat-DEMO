// Slot «polish» Ukrainian keys: the same keys and {placeholders} as polish.en.ts (typed). Wording: TERMS-UK.md
// («статистично значущий / незначущий» next to p; «Суттєво» / «Поки несуттєво» only as card labels).
import type { UkOf } from '../messages';
import type { polishEn } from './polish.en';

export const polishUk: UkOf<typeof polishEn> = {
  'tools.layerVisibility': 'Видимість шару «{layer}»',
  'tools.layerVisibilityValue': '{value}: 0 % — лише підкладка, 100 % — шар повністю',
  'tools.fullLayer': 'шар повністю',
  'cardTip.trendTerm': 'Тренд цієї ділянки',
  'cardTip.trendNs': '{slope} за 10 років, {p} → поки несуттєво: тренд статистично незначущий. За {seasons} зміна не відрізняється від випадкових коливань погоди.',
  'cardTip.trendSigUp': '{slope} за 10 років, {p} → суттєво: тренд статистично значущий, розрив росте. За {seasons} таку зміну важко пояснити випадковою погодою. Це сигнал, а не вирок.',
  'cardTip.trendSigDown': '{slope} за 10 років, {p} → суттєво: тренд статистично значущий, розрив зменшується. За {seasons} таку зміну важко пояснити випадковою погодою. Це сигнал, а не вирок.',
  'cardTip.multiple': 'Якщо перевірити дуже багато ділянок, приблизно кожна 20-та виявиться статистично значущою випадково.',
  'cardTip.trendInsufficient': 'Тренд не рахуємо: є лише {seasons} із чистими знімками, а потрібно щонайменше 8.',
  'cardTip.gapTerm': 'Розрив з лісом тут',
  'cardTip.gapHot': 'Поверхня забудови ({name}) влітку вдень на {gap} гарячіша, ніж {forest}: середнє за {seasons} ({from}–{to}). Це температура поверхні (дахи, асфальт) за Landsat 8, не повітря.',
  'cardTip.gapCool': 'Поверхня ділянки ({name}) влітку вдень на {gap} прохолодніша, ніж {forest}: середнє за {seasons} ({from}–{to}). Це температура поверхні за Landsat 8, не повітря.',
  'cardTip.howLink': 'Як ми це рахуємо →',
  'details.m1': 'Що міряємо: температура поверхні',
  'details.m2': 'З чим порівнюємо: ліс-еталон',
  'details.m3': 'Чому мапа й картка відрізняються',
  'details.m4': 'Шви між знімками й медіана за літо',
  'details.m5': 'Тренд, значущість і що таке p',
  'details.m6': 'Чому зелені ділянки теж теплі',
  'credits.madeBy': 'Зроблено: {team}, {org}',
  'credits.dataLabel': 'Дані',
};
