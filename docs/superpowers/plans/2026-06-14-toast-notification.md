# Toast Notification 系统实现计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 为前端添加全局 Toast 通知系统和按钮 Loading 状态，提升异步操作的视觉反馈。

**Architecture:** 使用 Zustand 管理 Toast 状态，创建独立的 Toast 组件和容器，增强现有 Button 组件支持 loading 属性，改造 Rules 页面的所有异步操作。

**Tech Stack:** React, TypeScript, Zustand, Tailwind CSS, Lucide React, React Query

---

## 文件结构

```
frontend/src/
├── store/
│   └── toast.ts              # 新建 - Toast 状态管理
├── components/ui/
│   ├── button.tsx            # 修改 - 添加 loading 属性
│   ├── toast.tsx             # 新建 - Toast 单个组件
│   └── toast-container.tsx   # 新建 - Toast 容器
├── components/
│   └── Layout.tsx            # 修改 - 集成 ToastContainer
└── pages/
    └── Rules.tsx             # 修改 - 改造异步操作
```

---

## Task 1: 创建 Toast Store

**Files:**
- Create: `frontend/src/store/toast.ts`

- [ ] **Step 1: 创建 Toast Store 文件**

```typescript
import { create } from "zustand";

export interface Toast {
  id: string;
  type: "success" | "error" | "info";
  message: string;
  duration?: number;
}

interface ToastStore {
  toasts: Toast[];
  addToast: (toast: Omit<Toast, "id">) => void;
  removeToast: (id: string) => void;
}

export const useToastStore = create<ToastStore>((set) => ({
  toasts: [],
  addToast: (toast) => {
    const id = `toast-${Date.now()}-${Math.random().toString(36).slice(2, 9)}`;
    set((state) => ({
      toasts: [...state.toasts, { ...toast, id }],
    }));
    // Auto-remove after duration (default 4000ms)
    const duration = toast.duration ?? 4000;
    setTimeout(() => {
      set((state) => ({
        toasts: state.toasts.filter((t) => t.id !== id),
      }));
    }, duration);
  },
  removeToast: (id) => {
    set((state) => ({
      toasts: state.toasts.filter((t) => t.id !== id),
    }));
  },
}));
```

---

## Task 2: 创建 Toast 组件

**Files:**
- Create: `frontend/src/components/ui/toast.tsx`

- [ ] **Step 1: 创建 Toast 组件文件**

```typescript
import { X, CheckCircle, AlertCircle, Info } from "lucide-react";
import { cn } from "@/lib/utils";
import type { Toast } from "@/store/toast";

interface ToastProps {
  toast: Toast;
  onClose: () => void;
}

const toastStyles = {
  success: {
    bg: "bg-green-500/10",
    border: "border-green-500/20",
    text: "text-green-600 dark:text-green-400",
    icon: CheckCircle,
  },
  error: {
    bg: "bg-destructive/10",
    border: "border-destructive/20",
    text: "text-destructive",
    icon: AlertCircle,
  },
  info: {
    bg: "bg-blue-500/10",
    border: "border-blue-500/20",
    text: "text-blue-600 dark:text-blue-400",
    icon: Info,
  },
};

export function ToastItem({ toast, onClose }: ToastProps) {
  const style = toastStyles[toast.type];
  const Icon = style.icon;

  return (
    <div
      className={cn(
        "flex items-start gap-3 rounded-lg border p-4 shadow-lg",
        "animate-in slide-in-from-right-full duration-300",
        style.bg,
        style.border
      )}
    >
      <Icon className={cn("h-5 w-5 flex-shrink-0 mt-0.5", style.text)} />
      <p className={cn("flex-1 text-sm", style.text)}>{toast.message}</p>
      <button
        onClick={onClose}
        className={cn(
          "flex-shrink-0 rounded-md p-1 opacity-70 transition-opacity hover:opacity-100",
          style.text
        )}
      >
        <X className="h-4 w-4" />
      </button>
    </div>
  );
}
```

---

## Task 3: 创建 Toast Container 组件

**Files:**
- Create: `frontend/src/components/ui/toast-container.tsx`

- [ ] **Step 1: 创建 Toast Container 文件**

```typescript
import { useToastStore } from "@/store/toast";
import { ToastItem } from "@/components/ui/toast";

export function ToastContainer() {
  const { toasts, removeToast } = useToastStore();

  if (toasts.length === 0) return null;

  return (
    <div className="fixed bottom-4 right-4 z-50 flex flex-col gap-2 max-w-sm w-full pointer-events-none">
      {toasts.map((toast) => (
        <div key={toast.id} className="pointer-events-auto">
          <ToastItem toast={toast} onClose={() => removeToast(toast.id)} />
        </div>
      ))}
    </div>
  );
}
```

---

## Task 4: 增强 Button 组件支持 Loading 状态

**Files:**
- Modify: `frontend/src/components/ui/button.tsx`

- [ ] **Step 1: 修改 Button 组件添加 loading 属性**

完整替换 `frontend/src/components/ui/button.tsx` 内容：

```typescript
import * as React from "react";
import { cn } from "@/lib/utils";
import { Spinner } from "@/components/ui/spinner";

type Variant = "default" | "secondary" | "destructive" | "outline" | "ghost" | "link";
type Size = "default" | "sm" | "lg" | "icon";

const variantClasses: Record<Variant, string> = {
  default: "bg-primary text-primary-foreground hover:bg-primary/90",
  secondary: "bg-secondary text-secondary-foreground hover:bg-secondary/80",
  destructive: "bg-destructive text-destructive-foreground hover:bg-destructive/90",
  outline: "border border-input bg-background hover:bg-accent hover:text-accent-foreground",
  ghost: "hover:bg-accent hover:text-accent-foreground",
  link: "text-primary underline-offset-4 hover:underline",
};

const sizeClasses: Record<Size, string> = {
  default: "h-10 px-4 py-2",
  sm: "h-9 rounded-md px-3 text-xs",
  lg: "h-11 rounded-md px-8",
  icon: "h-10 w-10",
};

export interface ButtonProps extends React.ButtonHTMLAttributes<HTMLButtonElement> {
  variant?: Variant;
  size?: Size;
  loading?: boolean;
}

export const Button = React.forwardRef<HTMLButtonElement, ButtonProps>(
  ({ className, variant = "default", size = "default", loading, disabled, children, ...props }, ref) => (
    <button
      ref={ref}
      className={cn(
        "inline-flex items-center justify-center gap-2 whitespace-nowrap rounded-md text-sm font-medium",
        "transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring",
        "disabled:pointer-events-none disabled:opacity-50",
        variantClasses[variant],
        sizeClasses[size],
        className,
      )}
      disabled={disabled || loading}
      {...props}
    >
      {loading && <Spinner className="h-4 w-4" />}
      {children}
    </button>
  ),
);
Button.displayName = "Button";
```

---

## Task 5: 在 Layout 中集成 ToastContainer

**Files:**
- Modify: `frontend/src/components/Layout.tsx`

- [ ] **Step 1: 在 Layout.tsx 中添加 ToastContainer 导入和使用**

在文件顶部添加导入：

```typescript
import { ToastContainer } from "@/components/ui/toast-container";
```

在组件返回的 JSX 最后（`</div>` 闭合标签前）添加 ToastContainer：

找到第 120 行的 `</div>` 闭合标签，在其前面添加：

```typescript
      {/* Toast Container - 固定在右下角 */}
      <ToastContainer />
```

完整的 Layout 组件返回部分应该是：

```typescript
  return (
    <div className="flex min-h-screen bg-background">
      {/* Sidebar */}
      <aside className="hidden w-60 flex-col border-r bg-card md:flex">
        {/* ... existing sidebar code ... */}
      </aside>

      {/* Mobile header */}
      <div className="fixed inset-x-0 top-0 z-30 flex h-14 items-center gap-2 border-b bg-card px-4 md:hidden">
        {/* ... existing mobile header code ... */}
      </div>

      {/* Main content */}
      <main className="flex-1 overflow-auto pt-14 md:pt-0">
        <div className="container mx-auto max-w-7xl p-4 md:p-8">{children}</div>
      </main>

      {/* Toast Container - 固定在右下角 */}
      <ToastContainer />
    </div>
  );
```

---

## Task 6: 改造 Rules 页面的删除和切换操作

**Files:**
- Modify: `frontend/src/pages/Rules.tsx`

- [ ] **Step 1: 添加 toast store 导入**

在文件顶部的导入部分（第 1-11 行），添加：

```typescript
import { useToastStore } from "@/store/toast";
```

- [ ] **Step 2: 改造 toggleMutation**

找到第 24-27 行的 `toggleMutation`，替换为：

```typescript
  const toggleMutation = useMutation({
    mutationFn: (id: number) => rulesApi.toggle(id),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["rules"] });
      useToastStore.getState().addToast({
        type: "success",
        message: "Rule status updated",
      });
    },
    onError: (err: unknown) => {
      const axiosErr = err as { response?: { data?: { detail?: string } } };
      useToastStore.getState().addToast({
        type: "error",
        message: axiosErr.response?.data?.detail || "Failed to toggle rule",
      });
    },
  });
```

- [ ] **Step 3: 改造 deleteMutation**

找到第 29-32 行的 `deleteMutation`，替换为：

```typescript
  const deleteMutation = useMutation({
    mutationFn: (id: number) => rulesApi.delete(id),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["rules"] });
      useToastStore.getState().addToast({
        type: "success",
        message: "Rule deleted successfully",
      });
    },
    onError: (err: unknown) => {
      const axiosErr = err as { response?: { data?: { detail?: string } } };
      useToastStore.getState().addToast({
        type: "error",
        message: axiosErr.response?.data?.detail || "Failed to delete rule",
      });
    },
  });
```

- [ ] **Step 4: 改造 RuleRow 组件添加 loading 状态**

找到第 129-178 行的 `RuleRow` 组件，替换为：

```typescript
function RuleRow({
  rule,
  onToggle,
  onDelete,
  isToggling,
  isDeleting,
}: {
  rule: Rule;
  onToggle: () => void;
  onDelete: () => void;
  isToggling: boolean;
  isDeleting: boolean;
}) {
  return (
    <TableRow>
      <TableCell>
        <code className="text-xs">{rule.rule_id}</code>
        {!rule.is_builtin && <Badge variant="outline" className="ml-1 text-xs">custom</Badge>}
      </TableCell>
      <TableCell>
        <div>
          <p className="font-medium">{rule.name}</p>
          <p className="text-xs text-muted-foreground">{rule.description}</p>
        </div>
      </TableCell>
      <TableCell>
        <Badge variant="outline">{rule.category}</Badge>
      </TableCell>
      <TableCell>
        <Badge className={severityColor(rule.severity)}>{rule.severity}</Badge>
      </TableCell>
      <TableCell className="text-xs text-muted-foreground">
        {(rule.languages ?? []).join(", ")}
      </TableCell>
      <TableCell>
        <Badge variant={rule.enabled ? "default" : "secondary"}>
          {rule.enabled ? "Enabled" : "Disabled"}
        </Badge>
      </TableCell>
      <TableCell className="text-right">
        <div className="flex justify-end gap-1">
          <Button
            onClick={onToggle}
            variant="ghost"
            size="icon"
            loading={isToggling}
          >
            {isToggling ? null : <Power className="h-4 w-4" />}
          </Button>
          {!rule.is_builtin && (
            <Button
              onClick={onDelete}
              variant="ghost"
              size="icon"
              loading={isDeleting}
            >
              {isDeleting ? null : <Trash2 className="h-4 w-4 text-destructive" />}
            </Button>
          )}
        </div>
      </TableCell>
    </TableRow>
  );
}
```

- [ ] **Step 5: 更新 RulesPage 组件中的 RuleRow 调用**

找到第 113-120 行的 `filtered.map` 部分，替换为：

```typescript
              {filtered.map((rule) => (
                <RuleRow
                  key={rule.id}
                  rule={rule}
                  onToggle={() => toggleMutation.mutate(rule.id)}
                  onDelete={() => deleteMutation.mutate(rule.id)}
                  isToggling={toggleMutation.isPending && toggleMutation.variables === rule.id}
                  isDeleting={deleteMutation.isPending && deleteMutation.variables === rule.id}
                />
              ))}
```

---

## Task 7: 改造 Rules 页面的创建规则操作

**Files:**
- Modify: `frontend/src/pages/Rules.tsx`

- [ ] **Step 1: 改造 CreateRuleForm 中的 createMutation**

找到第 196-212 行的 `createMutation`，替换为：

```typescript
  const createMutation = useMutation({
    mutationFn: () => rulesApi.create(form),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["rules"] });
      useToastStore.getState().addToast({
        type: "success",
        message: "Rule created successfully",
      });
      onClose();
    },
    onError: (err: unknown) => {
      const axiosErr = err as { response?: { data?: { detail?: string } } };
      const message = axiosErr.response?.data?.detail
        || (err instanceof Error ? err.message : "Failed to create rule");
      useToastStore.getState().addToast({
        type: "error",
        message,
      });
    },
  });
```

- [ ] **Step 2: 移除 CreateRuleForm 中的本地 error 和 success state**

找到第 182-183 行的本地 state，可以删除：

```typescript
  const [error, setError] = useState<string | null>(null);
  const [success, setSuccess] = useState(false);
```

并移除相关的 UI 代码（第 311-321 行的 error 和 success 提示区块）。

- [ ] **Step 3: 简化 CreateRuleForm 的 Button onClick**

找到第 327-330 行的 Button onClick，简化为：

```typescript
            onClick={() => createMutation.mutate()}
```

移除 `setError(null);` 调用。

---

## Task 8: 验证实现

- [ ] **Step 1: 启动前端开发服务器**

Run: `cd frontend && npm run dev`

- [ ] **Step 2: 测试 Toast 功能**

在浏览器中打开 http://localhost:3000，登录后进入 Rules 页面：

1. 点击删除按钮测试 error toast（如果没有自定义规则，先创建一个）
2. 点击切换按钮测试 success toast
3. 创建重复规则测试 error toast
4. 验证 Toast 位置在右下角
5. 验证 Toast 4秒后自动消失
6. 验证按钮 loading 状态显示 Spinner

- [ ] **Step 3: 运行 TypeScript 类型检查**

Run: `cd frontend && npx tsc --noEmit`

Expected: No errors

---

## 实现清单

| Task | 描述 | 状态 |
|------|------|------|
| Task 1 | 创建 Toast Store | [ ] |
| Task 2 | 创建 Toast 组件 | [ ] |
| Task 3 | 创建 Toast Container | [ ] |
| Task 4 | 增强 Button 组件 | [ ] |
| Task 5 | 集成到 Layout | [ ] |
| Task 6 | 改造删除/切换操作 | [ ] |
| Task 7 | 改造创建操作 | [ ] |
| Task 8 | 验证实现 | [ ] |
