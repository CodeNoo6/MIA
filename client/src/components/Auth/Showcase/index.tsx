import { useEffect, useState } from 'react';
import { Pause, Play } from 'lucide-react';
import { useMediaQuery } from '@librechat/client';
import type { TranslationKeys } from '~/hooks';
import { PlatformSlide, SecuritySlide, SupportSlide } from './slides';
import { useLocalize } from '~/hooks';
import { cn } from '~/utils';

const ROTATION_MS = 8000;

const slideNames: TranslationKeys[] = [
  'com_auth_showcase_eyebrow',
  'com_auth_showcase_support_title',
  'com_auth_showcase_security_title',
];

export default function Showcase({ appTitle }: { appTitle: string }) {
  const localize = useLocalize();
  const prefersReducedMotion = useMediaQuery('(prefers-reduced-motion: reduce)');
  const [active, setActive] = useState(0);
  const [paused, setPaused] = useState(false);
  const [interacting, setInteracting] = useState(false);
  const rotating = !paused && !interacting && !prefersReducedMotion;

  useEffect(() => {
    if (!rotating) {
      return;
    }
    const timer = window.setTimeout(
      () => setActive((current) => (current + 1) % slideNames.length),
      ROTATION_MS,
    );
    return () => window.clearTimeout(timer);
  }, [rotating, active]);

  const slides = [
    <PlatformSlide key="platform" appTitle={appTitle} />,
    <SupportSlide key="support" />,
    <SecuritySlide key="security" />,
  ];

  return (
    <section
      aria-roledescription="carousel"
      aria-label={localize('com_auth_showcase_label')}
      onMouseEnter={() => setInteracting(true)}
      onMouseLeave={() => setInteracting(false)}
      onFocus={() => setInteracting(true)}
      onBlur={(event) => {
        if (!event.currentTarget.contains(event.relatedTarget)) {
          setInteracting(false);
        }
      }}
      className="hidden w-1/2 max-w-2xl flex-col justify-center gap-8 border-r border-border-light bg-surface-secondary px-12 py-10 lg:flex xl:px-16"
    >
      <div className="grid" aria-live={rotating ? 'off' : 'polite'}>
        {slides.map((slide, index) => (
          <div
            key={slide.key}
            role="group"
            aria-roledescription="slide"
            aria-label={localize('com_auth_showcase_slide', {
              0: index + 1,
              1: slides.length,
            })}
            aria-hidden={index !== active}
            className={cn(
              'col-start-1 row-start-1 flex flex-col justify-center gap-8 transition-[opacity,visibility] duration-700 motion-reduce:transition-none',
              index === active ? 'opacity-100' : 'invisible opacity-0',
            )}
          >
            {slide}
          </div>
        ))}
      </div>

      <div className="flex items-center gap-3">
        <button
          type="button"
          onClick={() => setPaused((value) => !value)}
          aria-label={localize(paused ? 'com_auth_showcase_play' : 'com_auth_showcase_pause')}
          className="flex size-8 items-center justify-center rounded-full border border-border-medium text-text-secondary hover:bg-surface-hover focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring-primary"
        >
          {paused ? (
            <Play className="size-4" aria-hidden="true" />
          ) : (
            <Pause className="size-4" aria-hidden="true" />
          )}
        </button>
        <div className="flex gap-2">
          {slideNames.map((name, index) => (
            <button
              key={name}
              type="button"
              onClick={() => setActive(index)}
              aria-label={localize('com_auth_showcase_go_to', { 0: localize(name) })}
              aria-current={index === active}
              className={cn(
                'h-2 rounded-full transition-all focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring-primary motion-reduce:transition-none',
                index === active ? 'w-8 bg-text-primary' : 'w-2 bg-border-heavy',
              )}
            />
          ))}
        </div>
      </div>
    </section>
  );
}
