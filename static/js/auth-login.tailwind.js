tailwind.config = {
  theme: {
    extend: {
      fontFamily: { sans: ['Inter', 'ui-sans-serif', 'system-ui'] },
      colors: {
        brand: { 400: '#60A5FA', 500: '#3B82F6', 600: '#2563EB' },
        surface: '#F8FAFC',
        border: '#E2E8F0',
        ink: '#1E293B',
        muted: '#94A3B8',
      },
      boxShadow: {
        card: '0 2px 24px 0 rgba(15, 23, 42, 0.07)',
      },
    },
  },
};
