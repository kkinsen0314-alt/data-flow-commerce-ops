import { BarChart3, Bot, Clock4, Database, LayoutDashboard, ListChecks, MessageCircle, Puzzle, Settings, Wallet } from 'lucide-react';

export interface NavigationItem {
  path: string;
  icon: typeof MessageCircle;
  label: string;
  group: 'business' | 'system';
  requiresBilling?: boolean;
}

export const baseNavItems: NavigationItem[] = [
  { path: '/operations', icon: LayoutDashboard, label: '运营概览', group: 'business' },
  { path: '/operations/visualizations', icon: BarChart3, label: '数据看板', group: 'business' },
  { path: '/operations/conversations', icon: MessageCircle, label: '运营对话', group: 'business' },
  { path: '/operations/tasks', icon: ListChecks, label: '分析任务', group: 'business' },
  { path: '/operations/data-sources', icon: Database, label: '数据源', group: 'business' },
  { path: '/chat', icon: Bot, label: '智能体工作台', group: 'system' },
  { path: '/agent-profiles', icon: Bot, label: '智能体配置', group: 'system' },
  { path: '/capabilities', icon: Puzzle, label: '能力库', group: 'system' },
  { path: '/tasks', icon: Clock4, label: '自动化任务', group: 'system' },
  { path: '/usage', icon: BarChart3, label: '用量统计', group: 'system' },
  { path: '/billing', icon: Wallet, label: '账单', group: 'system', requiresBilling: true },
  { path: '/settings', icon: Settings, label: '设置', group: 'system' },
];

export function filterNavItems(billingEnabled: boolean) {
  return baseNavItems.filter((item) => !item.requiresBilling || billingEnabled);
}
