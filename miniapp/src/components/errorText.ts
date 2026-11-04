import { assertNever } from '../api/types';
import type { ApiError, ApiErrorKind } from '../api/errors';
import type { TranslationKey } from '../i18n/en';

export interface ErrorCopy {
  title: TranslationKey;
  body: TranslationKey;
  retryable: boolean;
}

/** Friendly copy for each error kind. Exhaustive on purpose. */
export function errorCopy(error: ApiError): ErrorCopy {
  const kind: ApiErrorKind = error.kind;
  switch (kind) {
    case 'auth':
      return { title: 'error.auth.title', body: 'error.auth.body', retryable: false };
    case 'forbidden':
      return { title: 'error.forbidden.title', body: 'error.forbidden.body', retryable: false };
    case 'rate_limited':
      return { title: 'error.rate.title', body: 'error.rate.body', retryable: true };
    case 'unavailable':
    case 'timeout':
      return { title: 'error.unavailable.title', body: 'error.unavailable.body', retryable: true };
    case 'network':
      return { title: 'error.offline.title', body: 'error.offline.body', retryable: true };
    case 'not_found':
      return { title: 'error.notFound.title', body: 'error.notFound.body', retryable: false };
    case 'invalid':
      return { title: 'error.invalid.title', body: 'error.invalid.body', retryable: false };
    case 'server':
    case 'bad_response':
      return { title: 'error.generic.title', body: 'error.generic.body', retryable: true };
    default:
      return assertNever(kind);
  }
}
