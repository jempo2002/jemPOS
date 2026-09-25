tailwind.config = {
  theme: {
    extend: {
      fontFamily: { sans: ['Inter', 'ui-sans-serif', 'system-ui'] },
      colors: {
        brand: { 400: '#60A5FA', 500: '#3B82F6', 600: '#2563EB' },
        ink: '#1E293B',
        muted: '#57667A',
      },
      // Mismos valores que global.css / dashboard.css del POS.
      boxShadow: {
        pos: '0 2px 10px rgba(15, 23, 42, 0.05)',
        'pos-hover': '0 8px 24px rgba(15, 23, 42, 0.08)',
        'pos-btn': '0 4px 14px rgba(59, 130, 246, 0.3)',
        modal: '0 8px 40px rgba(15, 23, 42, 0.18)',
      },
    },
  },
};
