import * as React from "react"
import { Slot } from "@radix-ui/react-slot"
import { cva } from "class-variance-authority"
import { cn } from "@/lib/utils"

const buttonVariants = cva(
  "inline-flex items-center justify-center whitespace-nowrap rounded-md text-sm font-medium transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[var(--accent)] focus-visible:ring-offset-1 focus-visible:ring-offset-[var(--surface-bg)] disabled:pointer-events-none disabled:opacity-50",
  {
    variants: {
      variant: {
        default: "bg-[var(--content-fg)] text-[var(--content-bg)] hover:opacity-90",
        destructive: "bg-[var(--status-error)] text-white hover:opacity-90",
        outline: "border border-[var(--surface-border)] bg-[var(--surface-bg)] text-[var(--content-fg)] hover:bg-[var(--surface-secondary)]",
        secondary: "bg-[var(--surface-secondary)] text-[var(--content-fg)] hover:bg-[var(--surface-border-subtle)]",
        ghost: "text-[var(--content-fg-secondary)] hover:bg-[var(--surface-secondary)] hover:text-[var(--content-fg)]",
        link: "text-[var(--accent-text)] underline-offset-4 hover:underline",
        accent: "bg-[var(--accent)] text-[var(--accent-on)] hover:bg-[var(--accent-hover)]",
        sidebar: "bg-transparent text-[var(--content-fg-secondary)] border border-[var(--sidebar-border)] hover:bg-[var(--sidebar-hover)] hover:text-[var(--content-fg)]",
        toolbar: "bg-transparent text-[var(--content-fg-tertiary)] hover:bg-[var(--surface-secondary)] hover:text-[var(--content-fg)]",
      },
      size: {
        default: "h-10 px-4 py-2",
        sm: "h-8 rounded-md px-3 text-xs",
        lg: "h-11 rounded-md px-8",
        icon: "h-8 w-8",
      },
    },
    defaultVariants: {
      variant: "default",
      size: "default",
    },
  }
)

const Button = React.forwardRef(({ className, variant, size, asChild = false, ...props }, ref) => {
  const Comp = asChild ? Slot : "button"
  return (
    <Comp
      className={cn(buttonVariants({ variant, size, className }))}
      ref={ref}
      {...props}
    />
  )
})
Button.displayName = "Button"

export { Button, buttonVariants }
