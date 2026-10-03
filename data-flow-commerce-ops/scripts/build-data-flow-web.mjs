import { access, cp, mkdir, rename, rm } from 'node:fs/promises';
import path from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';

const scriptDirectory = path.dirname(fileURLToPath(import.meta.url));
const projectRoot = path.resolve(scriptDirectory, '..');
const nativeAppRoot = path.join(projectRoot, 'native_app');
const runtimeWebRoot = path.join(projectRoot, 'runtime', 'web');
const finalDist = path.join(runtimeWebRoot, 'dist');
const stagingDist = path.join(projectRoot, 'runtime', 'tmp', 'data-flow-web-dist');
const previousDist = path.join(projectRoot, 'runtime', 'tmp', 'data-flow-web-dist-previous');

function readOption(name) {
  const index = process.argv.indexOf(name);
  return index >= 0 ? process.argv[index + 1] : undefined;
}

function assertInsideProject(target, label) {
  const relative = path.relative(projectRoot, path.resolve(target));
  if (!relative || relative.startsWith('..') || path.isAbsolute(relative)) {
    throw new Error(`${label} must be a project017 child path.`);
  }
}

async function pathExists(target) {
  try {
    await access(target);
    return true;
  } catch {
    return false;
  }
}

function replaceExactly(source, expected, replacement, label) {
  const firstIndex = source.indexOf(expected);
  const lastIndex = source.lastIndexOf(expected);
  if (firstIndex < 0 || firstIndex !== lastIndex) {
    throw new Error(`MiniClaw overlay anchor mismatch: ${label}`);
  }
  return source.replace(expected, replacement);
}

function replacePatternExactly(source, pattern, replacement, label) {
  const matches = source.match(pattern);
  if (!matches || matches.length !== 1) {
    throw new Error(`MiniClaw overlay anchor mismatch: ${label}`);
  }
  return source.replace(pattern, replacement);
}

const defaultPlatformRoot = path.resolve(
  projectRoot,
  '..',
  'project014-miniclaw-deployment',
  'upstream',
  'miniclaw',
);
const platformRoot = path.resolve(
  readOption('--platform-root') || process.env.MINICLAW_PLATFORM_ROOT || defaultPlatformRoot,
);
const platformWebRoot = path.join(platformRoot, 'web');
const platformSourceRoot = path.join(platformWebRoot, 'src');
const operationsApiPort = Number(readOption('--api-port') || '3022');
if (!Number.isInteger(operationsApiPort) || operationsApiPort < 1 || operationsApiPort > 65535) {
  throw new Error('The operations API port must be between 1 and 65535.');
}
const dependencyWebRoot = platformWebRoot;

for (const requiredPath of [
  path.join(platformSourceRoot, 'App.tsx'),
  path.join(platformWebRoot, 'public'),
  path.join(dependencyWebRoot, 'node_modules', 'vite', 'dist', 'node', 'index.js'),
  path.join(dependencyWebRoot, 'node_modules', '@vitejs', 'plugin-react', 'dist', 'index.js'),
  path.join(dependencyWebRoot, 'node_modules', '@tailwindcss', 'vite', 'dist', 'index.mjs'),
]) {
  if (!(await pathExists(requiredPath))) {
    throw new Error(`Required MiniClaw web dependency is missing: ${requiredPath}`);
  }
}

assertInsideProject(nativeAppRoot, 'Native app root');
assertInsideProject(finalDist, 'Final web dist');
assertInsideProject(stagingDist, 'Staging web dist');
assertInsideProject(previousDist, 'Previous web dist');

const customDependencyNames = [
  'lucide-react',
  'react',
  'react-dom',
  'react-router-dom',
  'recharts',
];
const dependencyAliases = customDependencyNames.map((packageName) => ({
  find: packageName,
  replacement: path.join(dependencyWebRoot, 'node_modules', packageName),
}));

const { build } = await import(
  pathToFileURL(path.join(dependencyWebRoot, 'node_modules', 'vite', 'dist', 'node', 'index.js')).href
);
const react = (
  await import(
    pathToFileURL(
      path.join(dependencyWebRoot, 'node_modules', '@vitejs', 'plugin-react', 'dist', 'index.js'),
    ).href
  )
).default;
const tailwindcss = (
  await import(
    pathToFileURL(
      path.join(dependencyWebRoot, 'node_modules', '@tailwindcss', 'vite', 'dist', 'index.mjs'),
    ).href
  )
).default;

const transformedModules = new Set();
const requiredTransforms = new Set(['App.tsx', 'AppLayout.tsx', 'UnifiedSidebar.tsx', 'useTheme.ts']);
const normalizedPlatformSource = platformSourceRoot.replaceAll('\\', '/');
const normalizedNativeStyles = path.join(nativeAppRoot, 'src', 'styles.css').replaceAll('\\', '/');

const dataFlowOverlay = {
  name: 'project017-data-flow-overlay',
  enforce: 'pre',
  transform(source, id) {
    const normalizedId = id.replaceAll('\\', '/');
    if (normalizedId === normalizedNativeStyles) {
      return {
        code: replaceExactly(
          source,
          '@source "../../../project014-miniclaw-deployment/upstream/miniclaw/web/src/**/*.{ts,tsx}";',
          `@source "${normalizedPlatformSource}/**/*.{ts,tsx}";`,
          'native component style sources',
        ),
        map: null,
      };
    }
    if (!normalizedId.startsWith(`${normalizedPlatformSource}/`)) {
      return null;
    }

    let next = source;
    const fileName = path.basename(normalizedId);

    if (normalizedId.endsWith('/App.tsx')) {
      next = replaceExactly(
        next,
        "import { LoginPage } from './pages/LoginPage';",
        "import { DataFlowLoginPage as LoginPage } from '@dataflow/pages/DataFlowLoginPage';\nimport { OperationsEntryPage } from '@dataflow/pages/OperationsEntryPage';",
        'App login import',
      );
      next = replacePatternExactly(
        next,
        /      <Route\r?\n        path="\/chat\/:groupFolder\?"/g,
        '      <Route path="/operations/*" element={<OperationsEntryPage />} />\n      <Route\n        path="/chat/:groupFolder?"',
        'operations route',
      );
      next = replaceExactly(
        next,
        '<Route path="/register" element={<RegisterPage />} />',
        '<Route path="/register" element={<Navigate to="/login" replace />} />',
        'registration route',
      );
      next = replaceExactly(
        next,
        '<Route path="/" element={<Navigate to="/chat" replace />} />',
        '<Route path="/" element={<Navigate to="/operations" replace />} />',
        'root redirect',
      );
      next = replaceExactly(
        next,
        '<Route path="*" element={<Navigate to="/chat" replace />} />',
        '<Route path="*" element={<Navigate to="/operations" replace />} />',
        'fallback redirect',
      );
    }

    if (normalizedId.endsWith('/components/layout/AppLayout.tsx')) {
      next = replaceExactly(next, "import { BottomTabBar } from './BottomTabBar';", "import { DataFlowMobileNavigation } from '@dataflow/components/DataFlowNavigation';", 'mobile navigation import');
      next = replacePatternExactly(next, /  const hideMobileTabBar = .*;\r?\n/g, '', 'retired bottom bar visibility');
      next = replaceExactly(next, '<ConnectionBanner />', '{!isDesktop && <DataFlowMobileNavigation />}\n        <ConnectionBanner />', 'mobile header');
      next = replaceExactly(next, "`overflow-y-auto overflow-x-hidden overscroll-y-none ${hideMobileTabBar ? 'pb-6' : 'pb-nav-safe'}`", "'overflow-y-auto overflow-x-hidden overscroll-y-none'", 'mobile scroll padding');
      next = replaceExactly(next, '{!hideMobileTabBar && <BottomTabBar />}', '', 'retired bottom navigation');
      next = replaceExactly(
        next,
        "    const appName = appearance?.appName || 'Miniclaw';",
        "    const appName = appearance?.appName === 'Miniclaw' ? 'Data Flow' : appearance?.appName || 'Data Flow';",
        'document title brand',
      );
    }

    if (normalizedId.endsWith('/components/layout/UnifiedSidebar.tsx')) {
      next = replaceExactly(next, "import { NavLink, useNavigate, useLocation } from 'react-router-dom';", "import { useNavigate, useLocation } from 'react-router-dom';\nimport { DataFlowNavigation } from '@dataflow/components/DataFlowNavigation';", 'primary navigation import');
      next = replacePatternExactly(next, /import \{ useBillingStore \} from .*;\r?\n/g, '', 'navigation billing moved');
      next = replacePatternExactly(next, /import \{ filterNavItems \} from .*;\r?\n/g, '', 'navigation items moved');
      next = replacePatternExactly(next, /import \{ cn \} from .*;\r?\n/g, '', 'navigation class helper moved');
      next = replacePatternExactly(next, /  const billingEnabled = .*;\r?\n/g, '', 'navigation billing selector moved');
      next = replacePatternExactly(next, /  const navItems = useMemo\([\s\S]*?\r?\n  \);\r?\n/g, '', 'navigation memo moved');
      next = replacePatternExactly(next, /        <nav className="w-\[4\.5rem\][\s\S]*?\{\/\* Spacer \*\/\}\r?\n          <div className="flex-1" \/>/g, '        <DataFlowNavigation onToggleWorkspace={onToggleCollapse} workspaceCollapsed={collapsed}>', 'primary navigation shell');
      next = replaceExactly(next, '</nav>', '</DataFlowNavigation>', 'primary navigation closing');
      next = replaceExactly(next, 'onClick={() => setShowBugReport(true)}', 'aria-label="报告问题"\n                onClick={() => setShowBugReport(true)}', 'report button label');
      next = replaceExactly(next, '<button className="rounded-full', '<button aria-label="账户菜单" className="rounded-full', 'account button label');
      next = replacePatternExactly(next, /onClick=\{onToggleCollapse\}\r?\n\s+className=/g, 'aria-label="收起工作区列表"\n                onClick={onToggleCollapse}\n                className=', 'workspace toggle label');
      const expandedLogo = /\s*<img\s+src=\{`\$\{import\.meta\.env\.BASE_URL\}icons\/logo-text\.svg`\}\s+alt=\{appearance\?\.appName \|\| 'Miniclaw'\}\s+className="h-10"\s+\/>/m;
      if (!expandedLogo.test(next)) {
        throw new Error('MiniClaw overlay anchor mismatch: expanded sidebar brand');
      }
      next = next.replace(
        expandedLogo,
        '\n              <span className="text-base font-semibold tracking-tight text-foreground">工作区</span>',
      );
      next = replacePatternExactly(
        next,
        /  const appearance = useAuthStore\(\(s\) => s\.appearance\);\r?\n/g,
        '',
        'unused appearance selector',
      );
      next = next.replaceAll('icons/icon-192.png', 'data-flow-mark.svg');
      next = next.replaceAll('Miniclaw', 'Data Flow');
    }

    if (normalizedId.endsWith('/hooks/useTheme.ts')) {
      next = replaceExactly(next, "if (typeof window === 'undefined') return 'orange';", "if (typeof window === 'undefined') return 'default';", 'server color scheme');
      next = replaceExactly(next, "  return 'orange';", "  return 'default';", 'default color scheme');
      next = replaceExactly(next, "() => 'orange' as ColorScheme", "() => 'default' as ColorScheme", 'color scheme snapshot');
      next = replaceExactly(next, "if (s === 'orange') window.localStorage.removeItem(SCHEME_KEY);", "if (s === 'default') window.localStorage.removeItem(SCHEME_KEY);", 'color scheme persistence');
    }

    if (normalizedId.endsWith('/pages/SetupPage.tsx')) {
      next = next.replaceAll('icons/icon-192.png', 'data-flow-mark.svg');
      next = next.replaceAll('Miniclaw', 'Data Flow');
    }

    if (normalizedId.endsWith('/components/common/LogoLoading.tsx')) {
      next = next.replaceAll('icons/icon-192.png', 'data-flow-mark.svg');
      next = next.replaceAll('Miniclaw', 'Data Flow');
    }

    if (normalizedId.endsWith('/pages/ChatPage.tsx')) {
      next = next.replaceAll("appearance?.appName || 'Miniclaw'", "'Data Flow'");
    }

    if (next !== source) {
      transformedModules.add(fileName);
      return { code: next, map: null };
    }
    return null;
  },
};

await rm(stagingDist, { recursive: true, force: true });

await build({
  define: { __DATA_FLOW_API_PORT__: String(operationsApiPort) },
  root: nativeAppRoot,
  publicDir: path.join(platformWebRoot, 'public'),
  plugins: [dataFlowOverlay, react(), tailwindcss()],
  resolve: {
    alias: [
      { find: '@dataflow', replacement: path.join(nativeAppRoot, 'src') },
      { find: '@miniclaw', replacement: platformSourceRoot },
      { find: '@', replacement: platformSourceRoot },
      ...dependencyAliases,
    ],
    dedupe: customDependencyNames,
  },
  build: {
    outDir: stagingDist,
    emptyOutDir: true,
    sourcemap: false,
  },
});

const missingTransforms = [...requiredTransforms].filter(
  (item) => !transformedModules.has(item),
);
if (missingTransforms.length > 0) {
  throw new Error(
    `Required Data Flow overlay transforms did not run: ${missingTransforms.join(', ')}`,
  );
}

await cp(path.join(nativeAppRoot, 'public'), stagingDist, {
  recursive: true,
  force: true,
});

await mkdir(runtimeWebRoot, { recursive: true });
await rm(previousDist, { recursive: true, force: true });
const hadCurrentDist = await pathExists(finalDist);
if (hadCurrentDist) {
  await rename(finalDist, previousDist);
}

try {
  await rename(stagingDist, finalDist);
} catch (error) {
  if (hadCurrentDist && !(await pathExists(finalDist)) && (await pathExists(previousDist))) {
    await rename(previousDist, finalDist);
  }
  throw error;
}

await rm(previousDist, { recursive: true, force: true });
process.stdout.write(`Data Flow web build ready: ${finalDist}\n`);
