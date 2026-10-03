import { useEffect, useState, type FormEvent } from 'react';
import { useNavigate } from 'react-router-dom';
import { ArrowRight, Check, Loader2, LockKeyhole, ShieldCheck } from 'lucide-react';
import { useAuthStore } from '@/stores/auth';
import { extractErrorMessage } from '@/utils/error';
import { Input } from '@/components/ui/input';
import { Button } from '@/components/ui/button';
import { Label } from '@/components/ui/label';
import { useTheme } from '@/hooks/useTheme';

export function DataFlowLoginPage() {
  useTheme();
  const [username, setUsername] = useState('');
  const [password, setPassword] = useState('');
  const [error, setError] = useState('');
  const [loading, setLoading] = useState(false);
  const navigate = useNavigate();
  const login = useAuthStore((state) => state.login);
  const initialized = useAuthStore((state) => state.initialized);
  const checkStatus = useAuthStore((state) => state.checkStatus);

  useEffect(() => {
    document.title = '登录 · Data Flow';
  }, []);

  useEffect(() => {
    if (initialized === null) {
      void checkStatus();
      return;
    }
    if (initialized === false) {
      navigate('/setup', { replace: true });
    }
  }, [checkStatus, initialized, navigate]);

  const handleLogin = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    setError('');
    setLoading(true);

    try {
      (window as { __authPrewarm?: unknown }).__authPrewarm = undefined;
      await login(username, password);
      const state = useAuthStore.getState();
      if (state.user?.role === 'admin' && state.setupStatus?.needsSetup) {
        navigate('/setup/providers', { replace: true });
        return;
      }
      navigate(state.user?.must_change_password ? '/settings' : '/operations', {
        replace: true,
      });
    } catch (loginError) {
      setError(extractErrorMessage(loginError) || '用户名或密码不正确');
    } finally {
      setLoading(false);
    }
  };

  if (initialized !== true) {
    return (
      <main className="df-auth-loading" aria-live="polite" aria-busy="true">
        <img src="/data-flow-mark.svg" alt="Data Flow" />
        <span>正在准备登录环境</span>
      </main>
    );
  }

  return (
    <main className="df-login-page">
      <div className="df-login-grid" aria-hidden="true" />
      <header className="df-login-header">
        <a className="df-brand" href="/login" aria-label="Data Flow 登录首页">
          <img src="/data-flow-mark.svg" alt="" />
          <span>
            <strong>Data Flow</strong>
            <small>电商运营分析</small>
          </span>
        </a>
        <span className="df-environment-badge">测试环境</span>
      </header>

      <section className="df-login-content" aria-labelledby="df-login-title">
        <div className="df-login-statement">
          <p className="df-login-eyebrow">DATA FLOW · 电商运营分析</p>
          <h1 id="df-login-title">
            让经营数据
            <span>流向明确行动</span>
          </h1>
          <p className="df-login-description">
            统一梳理短视频、直播、渠道线索、销售跟进与订单数据，形成可追溯的分析结果和执行建议。
          </p>
          <div className="df-login-principles" aria-label="平台能力">
            <div>
              <span><Check size={16} /></span>
              <p><strong>统一入口</strong>跨业务模块发起分析任务</p>
            </div>
            <div>
              <span><Check size={16} /></span>
              <p><strong>证据可查</strong>结论与指标口径清晰对应</p>
            </div>
            <div>
              <span><Check size={16} /></span>
              <p><strong>行动落地</strong>建议包含责任岗位与复验方式</p>
            </div>
          </div>
        </div>

        <div className="df-login-card">
          <div className="df-login-card-heading">
            <span className="df-login-lock"><LockKeyhole aria-hidden="true" /></span>
            <div>
              <h2>运营后台登录</h2>
              <p>使用 MiniClaw 本地账户验证身份</p>
            </div>
          </div>

          {error ? (
            <div className="df-login-error" role="alert">{error}</div>
          ) : null}

          <form onSubmit={handleLogin}>
            <div className="df-login-field">
              <Label htmlFor="data-flow-username">用户名</Label>
              <Input
                id="data-flow-username"
                name="username"
                type="text"
                autoComplete="username"
                autoFocus
                required
                value={username}
                onChange={(event) => setUsername(event.target.value)}
                placeholder="请输入用户名"
              />
            </div>
            <div className="df-login-field">
              <Label htmlFor="data-flow-password">密码</Label>
              <Input
                id="data-flow-password"
                name="password"
                type="password"
                autoComplete="current-password"
                required
                value={password}
                onChange={(event) => setPassword(event.target.value)}
                placeholder="请输入密码"
              />
            </div>
            <Button type="submit" disabled={loading} className="df-login-submit">
              {loading ? <Loader2 className="size-4 animate-spin" /> : null}
              <span>{loading ? '正在登录' : '登录工作台'}</span>
              {loading ? null : <ArrowRight className="size-4" />}
            </Button>
          </form>

          <div className="df-login-security">
            <ShieldCheck aria-hidden="true" />
            <span>账户由系统管理员统一配置，登录状态由 MiniClaw 本地认证服务管理。</span>
          </div>
        </div>
      </section>
    </main>
  );
}
