import {
  AudioLinesIcon,
  BotIcon,
  CableIcon,
  GaugeIcon,
  KeyRoundIcon,
  LayoutDashboardIcon,
  MessagesSquareIcon,
  PlugZapIcon,
  ScrollTextIcon,
  SettingsIcon,
  UsersIcon,
  type LucideIcon,
} from "lucide-react";

export interface NavItem {
  href: string;
  label: string;
  icon: LucideIcon;
  /** Hidden from viewers when the API only serves admins and owners. */
  adminOnly?: boolean;
}

export interface NavGroup {
  label: string;
  items: NavItem[];
}

export const NAV: NavGroup[] = [
  {
    label: "Voice",
    items: [
      { href: "/talk", label: "Talk", icon: AudioLinesIcon },
      { href: "/agents", label: "Agents", icon: BotIcon },
      { href: "/providers", label: "Providers", icon: CableIcon },
    ],
  },
  {
    label: "Monitor",
    items: [
      { href: "/", label: "Overview", icon: LayoutDashboardIcon },
      { href: "/sessions", label: "Sessions", icon: MessagesSquareIcon },
      { href: "/benchmarks", label: "Benchmarks", icon: GaugeIcon },
    ],
  },
  {
    label: "Connect",
    items: [
      { href: "/keys", label: "SDK keys", icon: KeyRoundIcon },
      { href: "/integrations", label: "Integrations", icon: PlugZapIcon },
    ],
  },
  {
    label: "Organisation",
    items: [
      { href: "/users", label: "Users", icon: UsersIcon, adminOnly: true },
      { href: "/audit", label: "Audit log", icon: ScrollTextIcon, adminOnly: true },
      { href: "/settings", label: "Settings", icon: SettingsIcon },
    ],
  },
];

export const NAV_ITEMS: NavItem[] = NAV.flatMap((g) => g.items);

/** The nav item a path belongs to: exact match for "/", prefix match otherwise. */
export function activeNavItem(pathname: string): NavItem | undefined {
  const path = pathname.replace(/\/+$/, "") || "/";
  if (path === "/") return NAV_ITEMS.find((i) => i.href === "/");
  return NAV_ITEMS.filter((i) => i.href !== "/" && (path === i.href || path.startsWith(`${i.href}/`))).sort(
    (a, b) => b.href.length - a.href.length,
  )[0];
}

export function isActive(item: NavItem, pathname: string): boolean {
  return activeNavItem(pathname)?.href === item.href;
}
