import * as React from "react";
import { cva, type VariantProps } from "class-variance-authority";
import { cn } from "@/lib/utils";
import { Toggle as TogglePrimitive } from "radix-ui";

const toggleVariants = cva(
  "inline-flex items-center justify-center gap-1.5 rounded-sm text-[13px] leading-4 font-medium whitespace-nowrap transition-colors duration-100 outline-none text-ink-muted hover:text-ink focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-focus-ring disabled:pointer-events-none disabled:opacity-50 [&_svg]:pointer-events-none [&_svg]:shrink-0 [&_svg:not([class*='size-'])]:size-4",
  {
    variants: {
      variant: {
        default:
          "bg-transparent hover:bg-surface-hover data-[state=on]:bg-primary-wash data-[state=on]:text-primary-ink",
        // one option of a segmented control: the picked one is raised out of the well
        outline:
          "bg-transparent data-[state=on]:bg-surface data-[state=on]:text-ink data-[state=on]:ring-1 data-[state=on]:ring-control-border dark:data-[state=on]:bg-surface-hover",
      },
      size: {
        default: "h-8 min-w-8 px-2",
        sm: "h-6 min-w-6 px-2",
        lg: "h-9 min-w-9 px-2.5",
      },
    },
    defaultVariants: {
      variant: "default",
      size: "default",
    },
  },
);

function Toggle({
  className,
  variant,
  size,
  ...props
}: React.ComponentProps<typeof TogglePrimitive.Root> & VariantProps<typeof toggleVariants>) {
  return (
    <TogglePrimitive.Root
      data-slot="toggle"
      className={cn(toggleVariants({ variant, size, className }))}
      {...props}
    />
  );
}

export { Toggle, toggleVariants };
