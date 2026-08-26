import { memo, type SVGProps } from "react";

type IconProps = SVGProps<SVGSVGElement> & { size?: number };

function make(name: string, children: React.ReactNode) {
  const Icon = memo(({ size = 16, ...rest }: IconProps) => (
    <svg
      width={size}
      height={size}
      viewBox="0 0 16 16"
      fill="none"
      stroke="currentColor"
      strokeWidth={1.6}
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
      {...rest}
    >
      {children}
    </svg>
  ));
  Icon.displayName = name;
  return Icon;
}

export const IconDashboard = make("IconDashboard", <>
  <rect x="1.5" y="1.5" width="5.5" height="5.5" rx="1" />
  <rect x="9" y="1.5" width="5.5" height="5.5" rx="1" />
  <rect x="1.5" y="9" width="5.5" height="5.5" rx="1" />
  <rect x="9" y="9" width="5.5" height="5.5" rx="1" />
</>);

export const IconTrade = make("IconTrade", <>
  <path d="M1.5 12.5 5.5 8l3 3 6-7" />
  <path d="M10.5 4h4v4" />
</>);

export const IconTechnique = make("IconTechnique", <>
  <path d="M2 12.5 5.5 8l2.5 2.5L11 5l3 3.5" />
  <path d="M2 3.5h12M2 6.5h5" opacity="0.5" />
</>);
export const IconArmed = make("IconArmed", <>
  <path d="M9 1.5 3.5 9h3L6.9 14.5 12.5 7h-3z" />
</>);
export const IconWatchlist = make("IconWatchlist", <>
  <path d="M2 3.5h8M2 8h8M2 12.5h8" />
  <path d="M12.5 2.5v4l2-1.3 2 1.3v-4z" transform="scale(0.78) translate(1.5 0)" />
  <circle cx="13" cy="10.5" r="1.6" opacity="0.6" />
</>);
export const IconSignals = make("IconSignals", <>
  <path d="M1.5 9.5h3.2l1.3 2.5h4l1.3-2.5h3.2" />
  <path d="M2.5 9.5v3a1.5 1.5 0 0 0 1.5 1.5h8a1.5 1.5 0 0 0 1.5-1.5v-3" />
  <path d="M8 2v6M5.5 5.5 8 8l2.5-2.5" />
</>);

export const IconPortfolios = make("IconPortfolios", <>
  <rect x="1.5" y="5" width="13" height="8.5" rx="1.5" />
  <path d="M5.5 5V3.5A1.5 1.5 0 0 1 7 2h2a1.5 1.5 0 0 1 1.5 1.5V5" />
  <path d="M1.5 8.5h13" />
</>);

export const IconJournal = make("IconJournal", <>
  <rect x="2.5" y="1.5" width="11" height="13" rx="1.5" />
  <path d="M5.5 5h5M5.5 8h5M5.5 11h3" />
</>);

export const IconSettings = make("IconSettings", <>
  <circle cx="8" cy="8" r="2.2" />
  <path d="M8 1.8v2M8 12.2v2M1.8 8h2M12.2 8h2M3.6 3.6l1.4 1.4M11 11l1.4 1.4M12.4 3.6 11 5M5 11l-1.4 1.4" />
</>);

export const IconCandles = make("IconCandles", <>
  <path d="M4.5 2v2M4.5 12v2M11.5 1.5v2M11.5 10.5v3" />
  <rect x="2.8" y="4" width="3.4" height="8" rx="0.8" />
  <rect x="9.8" y="3.5" width="3.4" height="7" rx="0.8" />
</>);

export const IconLine = make("IconLine", <>
  <path d="M1.5 10.5c2-4.5 3.5-4.5 5 0s3.5 4.5 5-5" />
  <path d="M13 4.5 14.5 3" />
</>);

export const IconEdit = make("IconEdit", <>
  <path d="m10.5 2.5 3 3L6 13l-3.6.6L3 10z" />
</>);

export const IconRefresh = make("IconRefresh", <>
  <path d="M13.5 8a5.5 5.5 0 1 1-1.6-3.9" />
  <path d="M13.7 1.8v3h-3" />
</>);

export const IconCheck = make("IconCheck", <>
  <path d="m2.5 8.5 3.5 3.5 7.5-8" />
</>);

export const IconX = make("IconX", <>
  <path d="m3.5 3.5 9 9M12.5 3.5l-9 9" />
</>);

export const IconClock = make("IconClock", <>
  <circle cx="8" cy="8" r="6.2" />
  <path d="M8 4.5V8l2.5 1.8" />
</>);

export const IconHalf = make("IconHalf", <>
  <circle cx="8" cy="8" r="6.2" />
  <path d="M8 1.8v12.4A6.2 6.2 0 0 0 8 1.8z" fill="currentColor" stroke="none" />
</>);

export const IconWarn = make("IconWarn", <>
  <path d="M8 2.2 14.8 13H1.2z" />
  <path d="M8 6.5v3M8 11.5v.01" />
</>);

export const IconOptions = make("IconOptions", <>
  <path d="M1.5 11.5h13" opacity="0.5" />
  <path d="M2 11.5 6.5 5l2.5 3.5L12 4l2.5 4" />
  <path d="M2.5 2.5h11" opacity="0.35" />
</>);

export const IconChevron = make("IconChevron", <>
  <path d="m5.5 3 5 5-5 5" />
</>);

export const IconSearch = make("IconSearch", <>
  <circle cx="7" cy="7" r="4.5" />
  <path d="m10.5 10.5 3.5 3.5" />
</>);
