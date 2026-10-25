import React from 'react';
import { RecoilRoot } from 'recoil';
import userEvent from '@testing-library/user-event';
import { MemoryRouter, Route, Routes } from 'react-router-dom';
import { render, screen, waitFor } from '@testing-library/react';
import * as reactQuery from 'librechat-data-provider/react-query';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import type { TLoginResponse, TLoginUser } from 'librechat-data-provider';
import * as authMutations from '~/data-provider/Auth/mutations';
import Registration from '~/components/Auth/Registration';
import 'test/matchMedia.mock';

jest.mock('librechat-data-provider/react-query');

jest.mock('react-router-dom', () => ({
  ...jest.requireActual('react-router-dom'),
  useOutletContext: () => ({ startupConfig: { registrationEnabled: true }, isFetching: false }),
}));

type Callbacks = {
  onSuccess?: (data: unknown, vars: TLoginUser) => void;
  onError?: (error: unknown) => void;
};

/** Mounts /register the way the app does: under the router, without AuthContextProvider. */
function renderRegisterRoute(loginResult: 'success' | 'failure') {
  let registerOptions: Callbacks = {};
  let loginOptions: Callbacks = {};
  const loginMutate = jest.fn((vars: TLoginUser) => {
    if (loginResult === 'success') {
      loginOptions.onSuccess?.({ token: 't', user: {} } as TLoginResponse, vars);
      return;
    }
    loginOptions.onError?.(new Error('Email not verified'));
  });

  jest.spyOn(reactQuery, 'useRegisterUserMutation').mockImplementation((options) => {
    registerOptions = (options ?? {}) as Callbacks;
    return {
      mutate: (vars: TLoginUser) => registerOptions.onSuccess?.({}, vars),
    } as unknown as ReturnType<typeof reactQuery.useRegisterUserMutation>;
  });
  jest.spyOn(authMutations, 'useLoginUserMutation').mockImplementation((options) => {
    loginOptions = (options ?? {}) as Callbacks;
    return { mutate: loginMutate } as unknown as ReturnType<
      typeof authMutations.useLoginUserMutation
    >;
  });

  render(
    <QueryClientProvider client={new QueryClient()}>
      <RecoilRoot>
        <MemoryRouter initialEntries={['/register']}>
          <Routes>
            <Route path="/register" element={<Registration />} />
            <Route path="/c/new" element={<div data-testid="chat-route" />} />
          </Routes>
        </MemoryRouter>
      </RecoilRoot>
    </QueryClientProvider>,
  );
  return { loginMutate };
}

async function fillAndSubmit() {
  await userEvent.type(screen.getByRole('textbox', { name: /Full name/i }), 'Ana Pérez');
  await userEvent.type(screen.getByRole('textbox', { name: /Username/i }), 'anap');
  await userEvent.type(screen.getByRole('textbox', { name: /Email/i }), 'ana@mia.co');
  await userEvent.type(screen.getByTestId('password'), 'password123');
  await userEvent.type(screen.getByTestId('confirm_password'), 'password123');
  await userEvent.click(screen.getByRole('button', { name: /Submit registration/i }));
}

afterEach(() => jest.restoreAllMocks());

test('signs the new account in and opens a chat without an auth provider around /register', async () => {
  const { loginMutate } = renderRegisterRoute('success');
  await fillAndSubmit();

  expect(loginMutate).toHaveBeenCalledWith({ email: 'ana@mia.co', password: 'password123' });
  await waitFor(() => expect(screen.getByTestId('chat-route')).toBeInTheDocument());
});

test('falls back to a sign-in prompt when automatic sign-in is refused', async () => {
  renderRegisterRoute('failure');
  await fillAndSubmit();

  await waitFor(() =>
    expect(
      screen.getByText(/Your account was created\. Sign in to continue\./i),
    ).toBeInTheDocument(),
  );
  expect(screen.getByRole('link', { name: 'Login' })).toHaveAttribute('href', '/login');
});
