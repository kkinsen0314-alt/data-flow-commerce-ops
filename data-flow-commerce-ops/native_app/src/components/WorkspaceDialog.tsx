import { useRef, type ReactNode } from 'react';
import { Dialog, DialogContent } from '@/components/ui/dialog';

export function WorkspaceDialog({ open, onClose, busy = false, titleId, className, children }: {
  open: boolean;
  onClose: () => void;
  busy?: boolean;
  titleId: string;
  className: string;
  children: ReactNode;
}) {
  const returnFocus = useRef<HTMLElement | null>(null);
  return <Dialog open={open} onOpenChange={(next) => { if (!next && !busy) onClose(); }}>
    <DialogContent className={className} aria-labelledby={titleId} aria-describedby={undefined} showCloseButton={false} onOpenAutoFocus={() => { returnFocus.current = document.activeElement instanceof HTMLElement ? document.activeElement : null; }} onCloseAutoFocus={(event) => { event.preventDefault(); returnFocus.current?.focus(); }} onEscapeKeyDown={(event) => { if (busy) event.preventDefault(); }} onInteractOutside={(event) => { if (busy) event.preventDefault(); }}>{children}</DialogContent>
  </Dialog>;
}
