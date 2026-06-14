# 全局通知与交互反馈系统设计

**日期**: 2026-06-14
**状态**: 已批准
**范围**: 前端用户体验优化

---

## 一、概述

为 Rules 页面的异步操作（创建、删除、切换状态）提供清晰的视觉反馈，包括：
1. **按钮 Loading 状态** - 操作进行中时按钮显示 Spinner 并禁用
2. **全局 Toast 通知** - 操作完成后在右下角显示成功/失败消息

---

## 二、Toast Notification 系统

### 2.1 组件结构

```
frontend/src/
├── store/
│   └── toast.ts           # Zustand store
├── components/ui/
│   ├── toast.tsx          # Toast 单个组件
│   └── toast-container.tsx # Toast 容器（固定右下角）
```

### 2.2 Toast 类型

| 类型 | 样式 | 图标 | 用例 |
|------|------|------|------|
| `success` | 绿色背景 (`bg-green-500/10`)，绿色文字 (`text-green-600`) | `CheckCircle` | 操作成功 |
| `error` | 红色背景 (`bg-destructive/10`)，红色文字 (`text-destructive`) | `AlertCircle` | 操作失败 |
| `info` | 蓝色背景 (`bg-blue-500/10`)，蓝色文字 (`text-blue-600`) | `Info` | 通用提示 |

### 2.3 API 设计

```typescript
// store/toast.ts
interface Toast {
  id: string;
  type: 'success' | 'error' | 'info';
  message: string;
  duration?: number;  // 默认 4000ms
}

interface ToastStore {
  toasts: Toast[];
  addToast: (toast: Omit<Toast, 'id'>) => void;
  removeToast: (id: string) => void;
}
```

### 2.4 使用方式

```typescript
import { useToastStore } from '@/store/toast';

// 在 mutation 的回调中
useMutation({
  onSuccess: () => {
    useToastStore.getState().addToast({
      type: 'success',
      message: 'Rule created successfully',
    });
  },
  onError: (err) => {
    useToastStore.getState().addToast({
      type: 'error',
      message: err.response?.data?.detail || 'Failed to create rule',
    });
  },
});
```

### 2.5 容器定位

- 位置：右下角固定定位 (`fixed bottom-4 right-4`)
- 层级：最高层级 (`z-50`)
- 布局：垂直堆叠 (`flex flex-col gap-2`)
- 最大宽度：`max-w-sm`

---

## 三、Button Loading 状态

### 3.1 增强现有 Button 组件

```typescript
// components/ui/button.tsx
interface ButtonProps extends React.ButtonHTMLAttributes<HTMLButtonElement> {
  variant?: Variant;
  size?: Size;
  loading?: boolean;  // 新增
}
```

### 3.2 Loading 状态视觉效果

- 按钮自动添加 `disabled` 属性
- 在按钮内容前添加 `<Spinner className="h-4 w-4" />`
- 按钮内容保持可见，但可选降低透明度

### 3.3 使用方式

```typescript
<Button
  onClick={onDelete}
  loading={deleteMutation.isPending}
  variant="ghost"
  size="icon"
>
  <Trash2 className="h-4 w-4 text-destructive" />
</Button>
```

---

## 四、Rules.tsx 页面改造

### 4.1 需要改造的操作

| 操作 | 当前状态 | 改造后 |
|------|----------|--------|
| 创建规则 | 本地 error/success state | Button Loading + Toast |
| 删除规则 | 无反馈 | Button Loading + Toast |
| 切换规则状态 | 无反馈 | Button Loading + Toast |

### 4.2 Mutation 改造示例

```typescript
// Toggle mutation
const toggleMutation = useMutation({
  mutationFn: (id: number) => rulesApi.toggle(id),
  onSuccess: () => {
    queryClient.invalidateQueries({ queryKey: ['rules'] });
    useToastStore.getState().addToast({
      type: 'success',
      message: 'Rule status updated',
    });
  },
  onError: (err: unknown) => {
    const axiosErr = err as { response?: { data?: { detail?: string } } };
    useToastStore.getState().addToast({
      type: 'error',
      message: axiosErr.response?.data?.detail || 'Failed to toggle rule',
    });
  },
});

// Delete mutation
const deleteMutation = useMutation({
  mutationFn: (id: number) => rulesApi.delete(id),
  onSuccess: () => {
    queryClient.invalidateQueries({ queryKey: ['rules'] });
    useToastStore.getState().addToast({
      type: 'success',
      message: 'Rule deleted successfully',
    });
  },
  onError: (err: unknown) => {
    const axiosErr = err as { response?: { data?: { detail?: string } } };
    useToastStore.getState().addToast({
      type: 'error',
      message: axiosErr.response?.data?.detail || 'Failed to delete rule',
    });
  },
});
```

### 4.3 RuleRow 组件改造

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
      {/* ... 其他单元格 ... */}
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

---

## 五、全局集成

### 5.1 Toast Container 集成位置

在 `Layout.tsx` 中添加：

```typescript
import ToastContainer from '@/components/ui/toast-container';

export default function Layout({ children }: { children: React.ReactNode }) {
  return (
    <div className="min-h-screen bg-background">
      {/* Header */}
      <header>...</header>

      {/* Main content */}
      <main>{children}</main>

      {/* Toast Container - 固定在右下角 */}
      <ToastContainer />
    </div>
  );
}
```

### 5.2 CSS 变量复用

Toast 组件使用现有的 Tailwind CSS 变量：
- `bg-destructive` / `text-destructive` 用于错误
- 自定义绿色和蓝色用于成功和信息提示

---

## 六、实现清单

1. 创建 `frontend/src/store/toast.ts` - Zustand store
2. 创建 `frontend/src/components/ui/toast.tsx` - 单个 Toast 组件
3. 创建 `frontend/src/components/ui/toast-container.tsx` - Toast 容器
4. 修改 `frontend/src/components/ui/button.tsx` - 添加 loading 属性
5. 修改 `frontend/src/components/Layout.tsx` - 集成 ToastContainer
6. 修改 `frontend/src/pages/Rules.tsx` - 改造所有异步操作
7. 可选：应用到其他页面（Settings、Reviews 等）

---

## 七、设计决策记录

| 决策点 | 选择 | 理由 |
|--------|------|------|
| 通知系统类型 | 两者结合 | Loading 提供即时反馈，Toast 提供持久结果通知 |
| Toast 位置 | 右下角 | 不遮挡主要内容，符合现代 Web 应用习惯 |
| Button Loading | 禁用 + Spinner | 视觉反馈最明确，复用现有 Spinner 组件 |
| 状态管理 | Zustand | 与项目现有状态管理方案一致 |
| 图标库 | Lucide React | 与项目现有图标库一致 |
