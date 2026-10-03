import { useEffect, useState, type ReactNode } from 'react';
import { Link, NavLink, useLocation, useNavigate } from 'react-router-dom';
import { ChevronDown, LogOut, Menu, Plus, UserRound, X } from 'lucide-react';
import { useAuthStore } from '@/stores/auth';
import { useBillingStore } from '@/stores/billing';
import { filterNavItems } from '../navigationItems';
import { Sheet, SheetContent, SheetDescription, SheetTitle, SheetTrigger } from '@/components/ui/sheet';

function NavigationLinks({ onNavigate, onToggleWorkspace, workspaceCollapsed }: {
  onNavigate?: () => void;
  onToggleWorkspace?: () => void;
  workspaceCollapsed?: boolean;
}) {
  const location = useLocation();
  const billingEnabled = useBillingStore((state) => state.billingEnabled);
  const items = filterNavItems(billingEnabled);
  return <>
    <NavLink className="df-navigation-create" to="/operations/analysis" onClick={onNavigate}><Plus size={17} />新建分析</NavLink>
    {(['business', 'system'] as const).map((group) => <div className={`df-navigation-${group}`} key={group}>
      <p className="df-navigation-label">{group === 'business' ? '运营工作区' : '系统与管理'}</p>
      {items.filter((item) => item.group === group).map(({ path, icon: Icon, label }) => <div className="df-navigation-row" key={path}>
        <NavLink to={path} end={path === '/operations'} onClick={onNavigate} className="df-navigation-link"><Icon size={18} strokeWidth={1.75} /><span>{label}</span></NavLink>
        {path === '/chat' && location.pathname.startsWith('/chat') && onToggleWorkspace && <button className="df-navigation-toggle" type="button" onClick={onToggleWorkspace} aria-label={workspaceCollapsed ? '展开工作区列表' : '收起工作区列表'} aria-expanded={!workspaceCollapsed}><ChevronDown size={15} /></button>}
      </div>)}
    </div>)}
  </>;
}

export function DataFlowNavigation({ children, onToggleWorkspace, workspaceCollapsed }: {
  children?: ReactNode;
  onToggleWorkspace: () => void;
  workspaceCollapsed: boolean;
}) {
  const user = useAuthStore((state) => state.user);
  return <nav className="df-navigation" aria-label="主导航">
    <Link className="df-navigation-brand" to="/operations"><img src="/data-flow-mark.svg" alt="" /><span><strong>Data Flow</strong><small>电商运营工作区</small></span></Link>
    <div className="df-navigation-scroll"><NavigationLinks onToggleWorkspace={onToggleWorkspace} workspaceCollapsed={workspaceCollapsed} /></div>
    <div className="df-navigation-footer"><span className="df-navigation-identity"><strong>{user?.display_name || user?.username}</strong><small>{user?.role === 'admin' ? '管理员' : '运营人员'}</small></span>{children}</div>
  </nav>;
}

export function DataFlowMobileNavigation() {
  const [open, setOpen] = useState(false);
  const location = useLocation();
  const navigate = useNavigate();
  const user = useAuthStore((state) => state.user);
  useEffect(() => { setOpen(false); }, [location.pathname]);
  return <header className="df-mobile-header">
    <Link className="df-mobile-brand" to="/operations"><img src="/data-flow-mark.svg" alt="" /><strong>Data Flow</strong></Link>
    <Sheet open={open} onOpenChange={setOpen}>
      <SheetTrigger asChild><button className="df-icon-button" type="button" aria-label="打开导航"><Menu size={21} /></button></SheetTrigger>
      <SheetContent className="df-mobile-navigation" side="right" showCloseButton={false}>
        <div className="df-mobile-navigation-heading"><SheetTitle>Data Flow</SheetTitle><button className="df-icon-button" type="button" aria-label="关闭导航" onClick={() => setOpen(false)}><X size={20} /></button></div>
        <SheetDescription className="df-navigation-description">电商运营工作区</SheetDescription>
        <nav aria-label="移动端主导航"><NavigationLinks onNavigate={() => setOpen(false)} /></nav>
        <div className="df-mobile-account"><span><UserRound size={16} />{user?.display_name || user?.username}</span><button type="button" onClick={async () => { await useAuthStore.getState().logout(); setOpen(false); navigate('/login'); }}><LogOut size={16} />退出登录</button></div>
      </SheetContent>
    </Sheet>
  </header>;
}
