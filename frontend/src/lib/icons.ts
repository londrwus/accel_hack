// Maps the lucide icon names used in the API (Signal.icon, kebab-case) to components.
// Explicit map so the bundle doesn't pull in every lucide icon. Add names here if the backend sends new ones.
import {
  Award,
  Briefcase,
  ChartLine,
  Check,
  Circle,
  Eye,
  Handshake,
  Landmark,
  Layers,
  Link,
  Newspaper,
  Timer,
  TrendingUp,
  TriangleAlert,
  UserMinus,
  Users,
  Sunrise,
  Rocket,
  Globe,
  type LucideIcon,
} from "lucide-react";

const ICONS: Record<string, LucideIcon> = {
  "trending-up": TrendingUp,
  link: Link,
  users: Users,
  "chart-line": ChartLine,
  "triangle-alert": TriangleAlert,
  newspaper: Newspaper,
  award: Award,
  landmark: Landmark,
  handshake: Handshake,
  layers: Layers,
  "user-minus": UserMinus,
  timer: Timer,
  eye: Eye,
  briefcase: Briefcase,
  check: Check,
  sunrise: Sunrise,
  rocket: Rocket,
  globe: Globe,
};

export function iconFor(name: string | null | undefined): LucideIcon {
  return (name && ICONS[name]) || Circle;
}
