// Slot «polish» English keys: Роман's bug list 15.11 (card p, contextual card tips, layer slider, Details §6,
// credits, map-label click). Keys must not repeat a key from en.ts or another part (i18n.test.ts).
export const polishEn = {
  // P1-4: the «Шари» slider follows the active layer
  'tools.layerVisibility': 'Visibility: {layer}',
  'tools.layerVisibilityValue': '{value}: 0% — basemap only, 100% — full layer',
  'tools.fullLayer': 'full layer',
  // Володя 15.11: card tips built from THIS report (no «See also» chains)
  'cardTip.trendTerm': 'Trend of this area',
  'cardTip.trendNs': '{slope} per 10 years, {p} → not yet significant: the trend is not statistically significant. Over {seasons} the change cannot be told apart from random weather variation.',
  'cardTip.trendSigUp': '{slope} per 10 years, {p} → significant: the trend is statistically significant, the gap is growing. Over {seasons} random weather hardly explains such a change. A signal, not a verdict.',
  'cardTip.trendSigDown': '{slope} per 10 years, {p} → significant: the trend is statistically significant, the gap is shrinking. Over {seasons} random weather hardly explains such a change. A signal, not a verdict.',
  'cardTip.multiple': 'If very many areas are tested, about every 20th comes out statistically significant by chance.',
  'cardTip.trendInsufficient': 'No trend: only {seasons} with clear images, and at least 8 are needed.',
  'cardTip.gapTerm': 'The gap here',
  'cardTip.gapHot': 'In summer daytime the built-up surface of {name} is {gap} hotter than {forest}: the mean over {seasons} ({from}–{to}). This is surface temperature (roofs, asphalt) from Landsat 8, not air.',
  'cardTip.gapCool': 'In summer daytime the surface of {name} is {gap} cooler than {forest}: the mean over {seasons} ({from}–{to}). This is surface temperature from Landsat 8, not air.',
  'cardTip.howLink': 'How we compute it →',
  'details.m1': 'What we measure: surface temperature',
  'details.m2': 'What we compare with: the reference forest',
  'details.m3': 'Why the map and the card differ',
  'details.m4': 'Image seams and the summer median',
  'details.m5': 'Trend, significance and what p means',
  'details.m6': 'Why green areas are still warm',
  // P2-1: credits
  'credits.madeBy': 'Made by {team} from {org}',
  'credits.dataLabel': 'Data',
} as const;
