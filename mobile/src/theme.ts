import { useColorScheme } from 'react-native';

// The web app's surfaces and gain/loss inks (frontend/src/styles.css), with the brand's
// gold as the accent: the mark, the hero card and every primary control share it.
const dark = {
  bg: '#0d0d0d',
  surface: '#1a1a19',
  surface2: '#232322',
  surface3: '#2c2c2a',
  line: '#2c2c2a',
  text: '#ffffff',
  text2: '#c3c2b7',
  text3: '#898781',
  accent: '#f2b83b',
  onAccent: '#1c1400',
  up: '#2dbd2d',
  down: '#e8554f',
  warn: '#fab219',
  upFill: '#0ca30c',
  downFill: '#d03b3b',
  series: '#3987e5',
  series2: '#d95926',
  series3: '#199e70',
};

const light: typeof dark = {
  bg: '#f4f4f0',
  surface: '#fdfdfc',
  surface2: '#efeee9',
  surface3: '#e4e3dc',
  line: '#e3e1d8',
  text: '#171717',
  text2: '#4c4b47',
  text3: '#7d7b74',
  accent: '#946500',
  onAccent: '#ffffff',
  up: '#006300',
  down: '#c62f2f',
  warn: '#8a6100',
  upFill: '#0ca30c',
  downFill: '#d03b3b',
  series: '#2a78d6',
  series2: '#eb6834',
  series3: '#1baf7a',
};

export type Theme = typeof dark & { dark: boolean };

export function useTheme(): Theme {
  const scheme = useColorScheme();
  return scheme === 'light' ? { ...light, dark: false } : { ...dark, dark: true };
}

export const space = { xs: 4, sm: 8, md: 12, lg: 16, xl: 24 } as const;
export const radius = { sm: 8, md: 12, lg: 16 } as const;

/** Gain / loss / neutral ink for a signed number. */
export function toneColor(t: Theme, sign: 1 | 0 | -1): string {
  return sign > 0 ? t.up : sign < 0 ? t.down : t.text2;
}
