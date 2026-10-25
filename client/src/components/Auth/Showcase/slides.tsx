import {
  BookOpenCheck,
  Clock,
  GraduationCap,
  KeyRound,
  Lightbulb,
  LockKeyhole,
  ShieldCheck,
  TrendingUp,
} from 'lucide-react';
import type { LucideIcon } from 'lucide-react';
import type { TranslationKeys } from '~/hooks';
import { useLocalize } from '~/hooks';

type Feature = { icon: LucideIcon; title: TranslationKeys; description: TranslationKeys };
type Agent = Omit<Feature, 'icon'> & {
  area: TranslationKeys;
  icon?: LucideIcon;
  images?: string[];
};

const agents: Agent[] = [
  {
    icon: BookOpenCheck,
    area: 'com_auth_showcase_agent_institutional_area',
    title: 'com_auth_showcase_agent_institutional_title',
    description: 'com_auth_showcase_agent_institutional_desc',
  },
  {
    icon: Lightbulb,
    area: 'com_auth_showcase_agent_learning_area',
    title: 'com_auth_showcase_agent_learning_title',
    description: 'com_auth_showcase_agent_learning_desc',
  },
  {
    icon: TrendingUp,
    area: 'com_auth_showcase_agent_backtest_area',
    title: 'com_auth_showcase_backtest_title',
    description: 'com_auth_showcase_backtest_desc',
  },
  {
    images: ['assets/catlife.png', 'assets/doglife.png'],
    area: 'com_auth_showcase_agent_catlife_area',
    title: 'com_auth_showcase_agent_catlife_title',
    description: 'com_auth_showcase_agent_catlife_desc',
  },
];

const steps: Array<Omit<Feature, 'icon'>> = [
  { title: 'com_auth_showcase_step1_title', description: 'com_auth_showcase_step1_desc' },
  { title: 'com_auth_showcase_step2_title', description: 'com_auth_showcase_step2_desc' },
  { title: 'com_auth_showcase_step3_title', description: 'com_auth_showcase_step3_desc' },
];

const supportFeatures: Feature[] = [
  {
    icon: BookOpenCheck,
    title: 'com_auth_showcase_support_syllabus_title',
    description: 'com_auth_showcase_support_syllabus_desc',
  },
  {
    icon: GraduationCap,
    title: 'com_auth_showcase_support_teacher_title',
    description: 'com_auth_showcase_support_teacher_desc',
  },
  {
    icon: Clock,
    title: 'com_auth_showcase_support_hours_title',
    description: 'com_auth_showcase_support_hours_desc',
  },
];

const securityFeatures: Feature[] = [
  {
    icon: ShieldCheck,
    title: 'com_auth_showcase_security_account_title',
    description: 'com_auth_showcase_security_account_desc',
  },
  {
    icon: LockKeyhole,
    title: 'com_auth_showcase_security_private_title',
    description: 'com_auth_showcase_security_private_desc',
  },
  {
    icon: KeyRound,
    title: 'com_auth_showcase_security_keys_title',
    description: 'com_auth_showcase_security_keys_desc',
  },
];

function Intro({
  eyebrow,
  title,
  tagline,
}: {
  eyebrow: TranslationKeys;
  title: string;
  tagline: TranslationKeys;
}) {
  const localize = useLocalize();
  return (
    <header>
      <p className="text-xs font-semibold uppercase tracking-widest text-accent-primary">
        {localize(eyebrow)}
      </p>
      <h2 className="mt-3 text-4xl font-bold text-text-primary xl:text-5xl">{title}</h2>
      <p className="mt-4 max-w-md text-lg text-text-secondary">{localize(tagline)}</p>
    </header>
  );
}

function Features({ items }: { items: Feature[] }) {
  const localize = useLocalize();
  return (
    <ul className="grid gap-3">
      {items.map(({ icon: Icon, title, description }) => (
        <li
          key={title}
          className="flex gap-4 rounded-xl border border-border-light bg-surface-primary p-4"
        >
          <span className="flex size-10 shrink-0 items-center justify-center rounded-lg bg-surface-tertiary text-accent-primary">
            <Icon className="size-5" aria-hidden="true" />
          </span>
          <div>
            <p className="font-semibold text-text-primary">{localize(title)}</p>
            <p className="mt-1 text-sm text-text-secondary">{localize(description)}</p>
          </div>
        </li>
      ))}
    </ul>
  );
}

export function PlatformSlide({ appTitle }: { appTitle: string }) {
  const localize = useLocalize();
  return (
    <>
      <Intro
        eyebrow="com_auth_showcase_eyebrow"
        title={appTitle}
        tagline="com_auth_showcase_tagline"
      />
      <section>
        <h3 className="text-xs font-semibold uppercase tracking-widest text-text-tertiary">
          {localize('com_auth_showcase_agents_title')}
        </h3>
        <ul className="mt-3 grid grid-cols-2 gap-3">
          {agents.map(({ icon: Icon, images, area, title, description }) => (
            <li
              key={title}
              className="flex flex-col rounded-xl border border-border-light bg-surface-primary p-4"
            >
              {images != null ? (
                <span className="flex gap-2">
                  {images.map((image) => (
                    <img key={image} src={image} alt="" aria-hidden="true" className="size-10" />
                  ))}
                </span>
              ) : (
                <span className="flex size-10 items-center justify-center rounded-lg bg-surface-tertiary text-accent-primary">
                  {Icon && <Icon className="size-5" aria-hidden="true" />}
                </span>
              )}
              <p className="mt-3 text-xs font-semibold uppercase tracking-wider text-text-tertiary">
                {localize(area)}
              </p>
              <p className="mt-1 font-semibold text-text-primary">{localize(title)}</p>
              <p className="mt-1 text-sm text-text-secondary">{localize(description)}</p>
            </li>
          ))}
        </ul>
        <p className="mt-3 text-sm text-text-secondary">
          {localize('com_auth_showcase_more_agents')}
        </p>
      </section>
      <ol className="grid grid-cols-3 gap-4">
        {steps.map(({ title, description }, index) => (
          <li key={title} className="border-t-2 border-border-heavy pt-3">
            <span className="text-2xl font-bold text-accent-primary">{index + 1}</span>
            <p className="mt-1 text-sm font-semibold text-text-primary">{localize(title)}</p>
            <p className="mt-1 text-xs text-text-secondary">{localize(description)}</p>
          </li>
        ))}
      </ol>
    </>
  );
}

export function SupportSlide() {
  const localize = useLocalize();
  return (
    <>
      <Intro
        eyebrow="com_auth_showcase_support_eyebrow"
        title={localize('com_auth_showcase_support_title')}
        tagline="com_auth_showcase_support_tagline"
      />
      <Features items={supportFeatures} />
    </>
  );
}

export function SecuritySlide() {
  const localize = useLocalize();
  return (
    <>
      <Intro
        eyebrow="com_auth_showcase_security_eyebrow"
        title={localize('com_auth_showcase_security_title')}
        tagline="com_auth_showcase_security_tagline"
      />
      <Features items={securityFeatures} />
    </>
  );
}
